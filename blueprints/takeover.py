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
router = APIRouter(prefix="/api/v1", tags=["Takeover"])

# Legacy compatibility router without prefix for backward compatibility
legacy_router = APIRouter(tags=["Legacy Takeover"])
_logger = logger(__name__)

# Pydantic model for request validation
class TakeoverRequest(BaseModel):
    """Request model for takeover endpoint"""
    phone: str = Field(..., description="The phone number to take over")


@router.get("/takeover")
async def takeover_health():
    """Health check for takeover endpoint"""
    return "THIS ENDPOINT IS UP AND RUNNING"


@router.post("/takeover")
async def takeover_by_human(request_data: TakeoverRequest):
    """
    Takeover conversation by human agent
    
    This endpoint sets the human intervention flag and updates the LangGraph state
    to indicate that a human operator has taken over the conversation.
    """
    try:
        _logger.info(f"Taking over conversation for phone: {request_data.phone}")
        
        phone = request_data.phone.strip()
        if not phone:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Phone number is required"
            )

        _logger.info(f"Setting intervention flag for {phone}")
        with engine.begin() as conn:
            # Check if conversation exists
            result = conn.execute(
                select(conversation.c.id)
                .where(conversation.c.phone == str(phone))
            )
            conversation_id = result.scalar_one_or_none()
            
            if conversation_id is None:
                _logger.warning(f"No conversation found for {phone} during takeover")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"No conversation found for phone number {phone}"
                )
            
            # Set intervention flag in DB
            conn.execute(
                update(conversation)
                .where(conversation.c.phone == str(phone))
                .values(human_intervention_required=True)
            )
            _logger.info(f"Intervention flag set for {phone}")
        
        # CRITICAL FIX: Offload LangGraph update to Celery
        update_langgraph_state_task.apply_async(
            args=[phone, {"operator_active": True}],
            queue='state',
            priority=8  # High priority for state updates
        )
        _logger.info(f"Queued LangGraph state update for {phone}")
        
        return {"status": "takeover_complete"}
        
    except HTTPException as he:
        raise he
    except Exception as e:
        _logger.error(f"Takeover failed for {phone}: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": f"Takeover failed: {str(e)}"}
        )


# Legacy compatibility endpoints (without /api/v1/ prefix)
# These maintain backward compatibility with existing web interface

@legacy_router.get("/takeover")
async def legacy_takeover_health():
    """Health check for legacy takeover endpoint"""
    return "THIS ENDPOINT IS UP AND RUNNING"


@legacy_router.post("/takeover")
async def legacy_takeover_by_human(request_data: TakeoverRequest):
    """Legacy takeover endpoint for backward compatibility"""
    return await takeover_by_human(request_data)