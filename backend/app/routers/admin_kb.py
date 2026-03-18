"""
Admin routes for knowledge base management with user authentication
"""
from fastapi import APIRouter, HTTPException, status, Depends, Query, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from sqlalchemy.exc import SQLAlchemyError
import secrets
from datetime import datetime, timezone
from typing import List, Optional
import logging

from app.core.database import get_db
from app.models.database_models import KnowledgeBase, AuditLog
from app.auth.models import User
from app.auth.utils import authenticate_user
from app.admin.schemas import (
    KnowledgeBaseCreate,
    KnowledgeBaseUpdate,
    KnowledgeBaseResponse,
    AuditLogResponse,
    SuccessResponse,
    PaginatedResponse
)

# Constants
RESOURCE_TYPE_KB = "knowledge_base"
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 500

# Setup logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin"])
security = HTTPBasic()


def verify_admin(
    credentials: HTTPBasicCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """
    Verify admin credentials using database authentication
    
    Args:
        credentials: HTTP Basic credentials
        db: Database session
        
    Returns:
        Authenticated User object
        
    Raises:
        HTTPException: If authentication fails
    """
    user = authenticate_user(db, credentials.username, credentials.password)
    
    if not user:
        logger.warning(f"Failed admin authentication attempt: {credentials.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials or account locked",
            headers={"WWW-Authenticate": "Basic"},
        )
    
    # Check if user has admin or editor role
    if user.role not in ["admin", "editor"]:
        logger.warning(f"Unauthorized access attempt by {credentials.username} (role: {user.role})")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions. Admin or editor role required.",
        )
    
    return user


def log_audit(
    db: Session,
    user: User,
    action: str,
    resource_type: str,
    resource_id: str,
    details: dict,
    request: Optional[Request] = None
) -> None:
    """
    Log audit trail to database
    
    Args:
        db: Database session
        user: User performing the action
        action: Action performed (create, update, delete, etc.)
        resource_type: Type of resource being acted upon
        resource_id: ID of the resource
        details: Additional details about the action
        request: Optional FastAPI request object for IP and user agent
    """
    try:
        audit_log = AuditLog(
            user_id=user.username,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            ip_address=request.client.host if request else None,
            user_agent=request.headers.get("user-agent") if request else None,
            timestamp=datetime.now(timezone.utc)
        )
        db.add(audit_log)
        db.commit()
        logger.info(f"Audit log created: {user.username} - {action} - {resource_type}:{resource_id}")
    except SQLAlchemyError as e:
        logger.error(f"Failed to create audit log: {e}")
        db.rollback()
        # Don't raise exception - audit logging failure shouldn't break the main operation


@router.post("/login", response_model=SuccessResponse)
def admin_login(
    credentials: HTTPBasicCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> SuccessResponse:
    """
    Verify admin login credentials
    
    Returns success response if credentials are valid
    """
    user = verify_admin(credentials, db)
    return SuccessResponse(
        success=True,
        message="Login successful",
        data={"username": user.username, "role": user.role}
    )


@router.get("/knowledge-base", response_model=List[KnowledgeBaseResponse])
def get_knowledge_base(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Items per page"),
    category: Optional[str] = Query(None, description="Filter by category"),
    search: Optional[str] = Query(None, description="Search in title and content"),
    db: Session = Depends(get_db),
    user: User = Depends(verify_admin)
) -> List[KnowledgeBaseResponse]:
    """
    Get knowledge base articles with pagination and filtering
    
    Args:
        page: Page number (1-indexed)
        page_size: Number of items per page
        category: Optional category filter
        search: Optional search term
        db: Database session
        user: Authenticated user
        
    Returns:
        List of knowledge base articles
    """
    try:
        query = db.query(KnowledgeBase)
        
        # Apply filters
        if category:
            query = query.filter(KnowledgeBase.category == category)
        
        if search:
            search_pattern = f"%{search}%"
            query = query.filter(
                (KnowledgeBase.title.ilike(search_pattern)) |
                (KnowledgeBase.content.ilike(search_pattern))
            )
        
        # Get total count
        total = query.count()
        
        # Apply pagination
        offset = (page - 1) * page_size
        articles = query.order_by(desc(KnowledgeBase.created_at)).offset(offset).limit(page_size).all()
        
        logger.info(f"Retrieved {len(articles)} KB articles (page {page}/{((total-1)//page_size)+1}) by {user.username}")
        
        return articles
        
    except SQLAlchemyError as e:
        logger.error(f"Database error retrieving KB articles: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve knowledge base articles"
        )


@router.post("/knowledge-base", response_model=SuccessResponse, status_code=status.HTTP_201_CREATED)
def create_knowledge_base_entry(
    entry: KnowledgeBaseCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(verify_admin)
) -> SuccessResponse:
    """
    Create a new knowledge base article
    
    Args:
        entry: Knowledge base article data
        request: FastAPI request object
        db: Database session
        user: Authenticated user
        
    Returns:
        Success response with created article ID
    """
    try:
        # Generate article ID if not provided
        article_id = entry.article_id or f"kb_{int(datetime.now(timezone.utc).timestamp())}"
        
        # Check for duplicate article_id
        if db.query(KnowledgeBase).filter(KnowledgeBase.article_id == article_id).first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Article ID '{article_id}' already exists"
            )
        
        # Create new knowledge base entry
        kb_article = KnowledgeBase(
            article_id=article_id,
            title=entry.title,
            content=entry.content,
            category=entry.category,
            tags=entry.tags,
            meta_info=entry.meta_info,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        
        db.add(kb_article)
        db.commit()
        db.refresh(kb_article)
        
        # Log audit trail
        log_audit(
            db, user, "create", RESOURCE_TYPE_KB, str(kb_article.id),
            {"article_id": article_id, "title": kb_article.title, "category": kb_article.category},
            request
        )
        
        logger.info(f"KB article created: {article_id} by {user.username}")
        
        return SuccessResponse(
            success=True,
            message="Knowledge base article created successfully",
            data={"id": kb_article.id, "article_id": article_id}
        )
        
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error creating KB article: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create knowledge base article"
        )


@router.put("/knowledge-base/{kb_id}", response_model=SuccessResponse)
def update_knowledge_base_entry(
    kb_id: int,
    entry: KnowledgeBaseUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(verify_admin)
) -> SuccessResponse:
    """
    Update an existing knowledge base article
    
    Args:
        kb_id: Knowledge base article ID
        entry: Updated article data
        request: FastAPI request object
        db: Database session
        user: Authenticated user
        
    Returns:
        Success response
    """
    try:
        article = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
        
        if not article:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Knowledge base article {kb_id} not found"
            )
        
        # Store old values for audit
        old_values = {
            "title": article.title,
            "content": article.content[:100] + "..." if len(article.content) > 100 else article.content,
            "category": article.category
        }
        
        # Update fields (only those provided)
        update_data = entry.dict(exclude_unset=True)
        
        # Handle legacy field names
        if 'question' in update_data and update_data['question']:
            update_data['title'] = update_data.pop('question')
        if 'answer' in update_data and update_data['answer']:
            update_data['content'] = update_data.pop('answer')
        
        for field, value in update_data.items():
            if hasattr(article, field) and value is not None:
                setattr(article, field, value)
        
        article.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        
        # Log audit trail
        new_values = {
            "title": article.title,
            "content": article.content[:100] + "..." if len(article.content) > 100 else article.content,
            "category": article.category
        }
        
        log_audit(
            db, user, "update", RESOURCE_TYPE_KB, str(kb_id),
            {"article_id": article.article_id, "old_values": old_values, "new_values": new_values},
            request
        )
        
        logger.info(f"KB article updated: {article.article_id} by {user.username}")
        
        return SuccessResponse(
            success=True,
            message="Knowledge base article updated successfully"
        )
        
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error updating KB article {kb_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update knowledge base article"
        )


@router.delete("/knowledge-base/{kb_id}", response_model=SuccessResponse)
def delete_knowledge_base_entry(
    kb_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(verify_admin)
) -> SuccessResponse:
    """
    Delete a knowledge base article
    
    Args:
        kb_id: Knowledge base article ID
        request: FastAPI request object
        db: Database session
        user: Authenticated user
        
    Returns:
        Success response
    """
    try:
        article = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
        
        if not article:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Knowledge base article {kb_id} not found"
            )
        
        # Store article info before deletion
        article_info = {
            "article_id": article.article_id,
            "title": article.title,
            "category": article.category
        }
        
        # Log audit trail before deletion
        log_audit(
            db, user, "delete", RESOURCE_TYPE_KB, str(kb_id),
            article_info,
            request
        )
        
        db.delete(article)
        db.commit()
        
        logger.info(f"KB article deleted: {article_info['article_id']} by {user.username}")
        
        return SuccessResponse(
            success=True,
            message="Knowledge base article deleted successfully"
        )
        
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error deleting KB article {kb_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete knowledge base article"
        )


@router.get("/knowledge-base/audit-logs", response_model=List[AuditLogResponse])
def get_audit_logs(
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of logs to return"),
    resource_id: Optional[str] = Query(None, description="Filter by resource ID"),
    action: Optional[str] = Query(None, description="Filter by action type"),
    db: Session = Depends(get_db),
    user: User = Depends(verify_admin)
) -> List[AuditLogResponse]:
    """
    Get audit logs for knowledge base changes
    
    Args:
        limit: Maximum number of logs to return
        resource_id: Optional filter by resource ID
        action: Optional filter by action type
        db: Database session
        user: Authenticated user
        
    Returns:
        List of audit log entries
    """
    try:
        query = db.query(AuditLog).filter(AuditLog.resource_type == RESOURCE_TYPE_KB)
        
        if resource_id:
            query = query.filter(AuditLog.resource_id == resource_id)
        
        if action:
            query = query.filter(AuditLog.action == action)
        
        logs = query.order_by(desc(AuditLog.timestamp)).limit(limit).all()
        
        logger.info(f"Retrieved {len(logs)} audit logs by {user.username}")
        
        return logs
        
    except SQLAlchemyError as e:
        logger.error(f"Database error retrieving audit logs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve audit logs"
        )

