from fastapi import APIRouter, HTTPException, status, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional

from config import logger
from db import engine, conversation
from sqlalchemy import select, update
from tasks import update_langgraph_state_task
import json

# Main API router with v1 prefix
router = APIRouter(prefix="/api/v1", tags=["Handback"])

# Legacy compatibility router without prefix for backward compatibility
legacy_router = APIRouter(tags=["Legacy Handback"])
_logger = logger(__name__)

# Pydantic model for request validation
class HandbackRequest(BaseModel):
    """Request model for handback endpoint"""
    phone: str = Field(..., description="The phone number to hand back to AI")


@router.get("/handback")
async def handback_health():
    """Health check for handback endpoint"""
    return "THIS ENDPOINT IS UP AND RUNNING"


@router.post("/handback")
async def handback_to_ai(request_data: HandbackRequest):
    """
    Hand conversation back to AI
    
    This endpoint clears the human intervention flag and updates the LangGraph state
    to indicate that the AI should take over the conversation.
    """
    try:
        _logger.info(f"Handing back conversation to AI for phone: {request_data.phone}")
        
        phone = request_data.phone.strip()
        if not phone:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Phone number is required"
            )
        
        with engine.begin() as conn:
            # Check if conversation exists
            result = conn.execute(
                select(conversation.c.id)
                .where(conversation.c.phone == str(phone))
            )
            conversation_id = result.scalar_one_or_none()
            
            if conversation_id is None:
                _logger.warning(f"No conversation found for {phone} during handback")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"No conversation found for phone number {phone}"
                )
            
            # Clear intervention flag in DB
            conn.execute(
                update(conversation)
                .where(conversation.c.phone == str(phone))
                .values(human_intervention_required=False)
            )
            _logger.info(f"Intervention flag cleared for {phone}")
        
        # CRITICAL FIX: Offload LangGraph update to Celery
        # This prevents blocking the worker
        update_langgraph_state_task.apply_async(
            args=[phone, {"operator_active": False}],
            queue='state',
            priority=8  # High priority for state updates
        )
        _logger.info(f"Queued LangGraph state update for {phone}")
        
        return {"status": "handback_complete"}
        
    except HTTPException as he:
        raise he
    except Exception as e:
        _logger.error(f"Handback failed for {phone}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Handback failed: {str(e)}"
        )


# Legacy compatibility endpoints (without /api/v1/ prefix)
# These maintain backward compatibility with existing web interface

@legacy_router.get("/handback")
async def legacy_handback_health():
    """Health check for legacy handback endpoint"""
    return "THIS ENDPOINT IS UP AND RUNNING"


@legacy_router.post("/handback")
async def legacy_handback_to_ai(request_data: HandbackRequest):
    """Legacy handback endpoint for backward compatibility"""
    return await handback_to_ai(request_data)