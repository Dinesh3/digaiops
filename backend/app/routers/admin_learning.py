"""
Admin endpoint for managing auto-learning and knowledge base
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.services.auto_learning_service import (
    get_auto_learned_stats,
    update_article_from_feedback,
    generate_embedding
)
from app.models.database_models import KnowledgeBase

router = APIRouter()


@router.get("/admin/learning/stats")
async def get_learning_dashboard(db: Session = Depends(get_db)):
    """Get comprehensive statistics on auto-learning"""
    stats = get_auto_learned_stats(db=db)
    
    # Add more stats
    total_articles = db.query(KnowledgeBase).count()
    articles_with_embeddings = db.query(KnowledgeBase).filter(
        KnowledgeBase.embedding.isnot(None)
    ).count()
    
    stats.update({
        "total_articles": total_articles,
        "articles_with_embeddings": articles_with_embeddings,
        "embedding_coverage": round(articles_with_embeddings / total_articles * 100, 2) if total_articles > 0 else 0
    })
    
    return stats


@router.post("/admin/learning/generate-embeddings")
async def generate_all_embeddings(
    force: bool = False,
    db: Session = Depends(get_db)
):
    """
    Generate embeddings for all articles that don't have them
    
    Query params:
        force: If true, regenerate embeddings for all articles (even if they exist)
    """
    from sentence_transformers import SentenceTransformer
    
    try:
        model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Could not load embedding model: {str(e)}"
        )
    
    # Get articles to process
    if force:
        articles = db.query(KnowledgeBase).all()
    else:
        articles = db.query(KnowledgeBase).filter(
            KnowledgeBase.embedding.is_(None)
        ).all()
    
    if not articles:
        return {
            "status": "success",
            "message": "All articles already have embeddings",
            "processed": 0
        }
    
    # Generate embeddings
    processed = 0
    errors = 0
    
    for article in articles:
        try:
            text = f"{article.title}. {article.content}"
            embedding = model.encode(text, convert_to_numpy=True).tolist()
            
            article.embedding = embedding
            processed += 1
            
            if processed % 10 == 0:
                db.commit()  # Commit in batches
                
        except Exception as e:
            print(f"❌ Failed to generate embedding for article {article.id}: {e}")
            errors += 1
    
    db.commit()  # Final commit
    
    return {
        "status": "success",
        "message": f"Generated embeddings for {processed} articles",
        "processed": processed,
        "errors": errors,
        "total_articles": db.query(KnowledgeBase).count(),
        "with_embeddings": db.query(KnowledgeBase).filter(
            KnowledgeBase.embedding.isnot(None)
        ).count()
    }


@router.post("/admin/learning/update-article/{article_id}")
async def update_knowledge_article(
    article_id: int,
    improved_answer: str,
    db: Session = Depends(get_db)
):
    """Update an existing article with improved content"""
    success = update_article_from_feedback(
        article_id=article_id,
        improved_answer=improved_answer,
        db=db
    )
    
    if not success:
        raise HTTPException(status_code=404, detail="Article not found")
    
    return {
        "status": "success",
        "message": f"Updated article {article_id}"
    }


@router.delete("/admin/learning/article/{article_id}")
async def delete_article(article_id: int, db: Session = Depends(get_db)):
    """Delete an article from knowledge base"""
    article = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == article_id
    ).first()
    
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    
    db.delete(article)
    db.commit()
    
    return {
        "status": "success",
        "message": f"Deleted article: {article.title}"
    }


@router.get("/admin/learning/articles")
async def list_all_articles(
    category: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """List all articles in knowledge base with optional filtering"""
    query = db.query(KnowledgeBase)
    
    if category:
        query = query.filter(KnowledgeBase.category == category)
    
    articles = query.order_by(
        KnowledgeBase.created_at.desc()
    ).offset(skip).limit(limit).all()
    
    return {
        "total": query.count(),
        "articles": [
            {
                "id": a.id,
                "title": a.title,
                "content": a.content[:200] + "..." if len(a.content) > 200 else a.content,
                "category": a.category,
                "tags": a.tags,
                "has_embedding": a.embedding is not None,
                "created_at": a.created_at.isoformat() if a.created_at else None
            }
            for a in articles
        ]
    }
