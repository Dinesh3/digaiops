# Vector-based semantic search for chatbot knowledge base using PostgreSQL
import os
from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
import numpy as np

from app.config.database import get_db
from app.models.database_models import KnowledgeBase

router = APIRouter()

# Lazy loading for sentence transformer (only load if explicitly enabled)
embedding_model = None
ENABLE_SEMANTIC_SEARCH = os.getenv('ENABLE_SEMANTIC_SEARCH', 'false').lower() == 'true'

def _load_embedding_model():
    """Lazy load the sentence transformer model only when needed"""
    global embedding_model
    if embedding_model is None and ENABLE_SEMANTIC_SEARCH:
        try:
            from sentence_transformers import SentenceTransformer
            # Configure HuggingFace
            os.environ['HF_ENDPOINT'] = os.getenv('HF_ENDPOINT', 'https://huggingface.co')
            os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
            
            embedding_model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
            print("✅ Embedding model loaded for search endpoint")
        except Exception as e:
            print(f"⚠️ Could not load embedding model: {e}")
            embedding_model = False  # Mark as failed
    return embedding_model

@router.post("/chatbot/search")
async def chatbot_search(request: Request, db: Session = Depends(get_db)):
    """
    Search in knowledge base using keyword matching (and optionally semantic vector embeddings)
    
    Returns top 5 most relevant articles
    """
    data = await request.json()
    query = data.get("query", "")
    
    if not query:
        return JSONResponse({"results": []})
    
    # Try to load embedding model (only if ENABLE_SEMANTIC_SEARCH=true)
    model = _load_embedding_model()
    
    # If embedding model is not available, use improved keyword search
    if not model or model is False:
        query_lower = query.lower().strip()
        articles = db.query(KnowledgeBase).all()
        
        # Detect if query is a question or just a keyword
        is_question = any(query_lower.startswith(q) for q in ['what', 'how', 'why', 'when', 'where', 'who']) or '?' in query
        
        # Score each article by relevance
        scored_articles = []
        for article in articles:
            title_lower = article.title.lower()
            content_lower = article.content.lower()
            score = 0
            
            # Exact title match (highest priority)
            if query_lower == title_lower:
                score += 100
            # Question format matching
            elif is_question and title_lower.startswith('what is') and query_lower.startswith('what is'):
                query_subject = query_lower.replace('what is', '').strip().rstrip('?')
                title_subject = title_lower.replace('what is', '').strip().rstrip('?')
                if query_subject == title_subject or query_subject in title_subject or title_subject in query_subject:
                    score += 90
            # For single keywords, boost "what is" explanatory articles
            elif not is_question and len(query_lower.split()) == 1:
                if title_lower.startswith('what is'):
                    title_subject = title_lower.replace('what is', '').replace('a ', '').replace('an ', '').replace('the ', '').strip().rstrip('?')
                    if query_lower in title_subject.split():
                        score += 80
            # Title starts with query
            elif title_lower.startswith(query_lower):
                score += 50
            # Query is a word in title
            elif f" {query_lower} " in f" {title_lower} " or title_lower.startswith(f"{query_lower} ") or title_lower.endswith(f" {query_lower}"):
                score += 30
            # Query appears anywhere in title
            elif query_lower in title_lower:
                score += 20
            
            # Content matches (lower priority, reduced impact)
            content_occurrences = content_lower.count(query_lower)
            score += min(content_occurrences * 1, 5)
            
            # Bonus for longer content if it's a question
            if is_question and score > 0 and len(content_lower) > 200:
                score += 10
            # Bonus for shorter, focused articles for keywords
            elif not is_question and score > 0 and len(content_lower) < 300:
                score += 5
            
            if score > 0:
                scored_articles.append((score, article))
        
        # Sort by score descending and return top 5
        scored_articles.sort(key=lambda x: x[0], reverse=True)
        results = [
            {
                "question": article.title,
                "answer": article.content,
                "score": round(score / 100, 2),  # Normalize to 0-1 range
                "category": article.category,
                "method": "keyword"
            }
            for score, article in scored_articles[:5]
        ]
        return JSONResponse({"results": results, "method": "keyword", "semantic_search_enabled": False})
    
    
    # Generate query embedding for semantic search
    try:
        query_embedding = model.encode(query, convert_to_numpy=True)
    except Exception as e:
        return JSONResponse({
            "results": [],
            "error": f"Failed to generate query embedding: {str(e)}"
        })
    
    # Query knowledge base articles with embeddings
    articles = db.query(KnowledgeBase).filter(
        KnowledgeBase.embedding.isnot(None)
    ).all()
    
    if not articles:
        # Fallback to improved keyword search if no embeddings exist
        query_lower = query.lower().strip()
        all_articles = db.query(KnowledgeBase).all()
        
        # Detect if query is a question or just a keyword
        is_question = any(query_lower.startswith(q) for q in ['what', 'how', 'why', 'when', 'where', 'who']) or '?' in query
        
        scored_articles = []
        for article in all_articles:
            title_lower = article.title.lower()
            content_lower = article.content.lower()
            score = 0
            
            # Exact title match
            if query_lower == title_lower:
                score += 100
            # Question format matching
            elif is_question and title_lower.startswith('what is') and query_lower.startswith('what is'):
                query_subject = query_lower.replace('what is', '').strip().rstrip('?')
                title_subject = title_lower.replace('what is', '').strip().rstrip('?')
                if query_subject == title_subject or query_subject in title_subject or title_subject in query_subject:
                    score += 90
            # For single keywords, boost "what is" explanatory articles
            elif not is_question and len(query_lower.split()) == 1:
                if title_lower.startswith('what is'):
                    title_subject = title_lower.replace('what is', '').replace('a ', '').replace('an ', '').replace('the ', '').strip().rstrip('?')
                    if query_lower in title_subject.split():
                        score += 80
            elif title_lower.startswith(query_lower):
                score += 50
            elif f" {query_lower} " in f" {title_lower} " or title_lower.startswith(f"{query_lower} ") or title_lower.endswith(f" {query_lower}"):
                score += 30
            elif query_lower in title_lower:
                score += 20
            
            # Content matches (reduced impact)
            content_occurrences = content_lower.count(query_lower)
            score += min(content_occurrences * 1, 5)
            
            # Bonus for questions vs keywords
            if is_question and score > 0 and len(content_lower) > 200:
                score += 10
            elif not is_question and score > 0 and len(content_lower) < 300:
                score += 5
            
            if score > 0:
                scored_articles.append((score, article))
        
        scored_articles.sort(key=lambda x: x[0], reverse=True)
        results = [
            {
                "question": article.title,
                "answer": article.content,
                "score": round(score / 100, 2),
                "category": article.category,
                "method": "keyword_fallback"
            }
            for score, article in scored_articles[:5]
        ]
        return JSONResponse({
            "results": results,
            "message": "No articles with embeddings found. Using keyword search.",
            "method": "keyword_fallback"
        })
    
    # Calculate cosine similarity for each article
    scored_articles = []
    for article in articles:
        if article.embedding:
            try:
                # Convert stored embedding to numpy array
                article_embedding = np.array(article.embedding)
                
                # Calculate cosine similarity
                similarity = np.dot(query_embedding, article_embedding) / (
                    np.linalg.norm(query_embedding) * np.linalg.norm(article_embedding)
                )
                
                scored_articles.append({
                    "question": article.title,
                    "answer": article.content,
                    "score": float(similarity),
                    "category": article.category,
                    "tags": article.tags,
                    "method": "semantic"
                })
            except Exception as e:
                print(f"Error calculating similarity for article {article.id}: {e}")
                continue
    
    # Sort by similarity score (descending) and take top 5
    scored_articles.sort(key=lambda x: x["score"], reverse=True)
    top_results = scored_articles[:5]
    
    # Filter out low-confidence results (< 0.3 similarity)
    filtered_results = [r for r in top_results if r["score"] > 0.3]
    
    return JSONResponse({
        "results": filtered_results,
        "total_articles": len(articles),
        "method": "semantic_vector",
        "semantic_search_enabled": True
    })

