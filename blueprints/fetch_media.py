from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from config import logger
from utility.whatsapp import get_url
from utility.media_cache_manager import get_media_cache
from datetime import datetime

router = APIRouter()
_logger = logger(__name__)


@router.get("/media")
async def fetch_media(
    id: str = Query(..., description="WhatsApp media ID"),
    timestamp: int = Query(None, description="Optional Unix timestamp of message")
):
    """
    Fetch media URL from WhatsApp API with caching support
    
    Args:
        id: WhatsApp media ID from incoming message
        timestamp: Optional Unix timestamp for expiration check
        
    Returns:
        JSON response with media URL and metadata
        
    Raises:
        HTTPException: If media ID is invalid or fetch fails
    """
    if not id:
        raise HTTPException(
            status_code=400,
            detail="Missing media ID parameter"
        )
    
    _logger.info(f"Fetching media URL for ID: {id}")
    
    # Get cache manager for statistics
    cache = get_media_cache()
    cache._increment_stat("total_requests")
    
    # Convert timestamp if provided
    dt_timestamp = None
    if timestamp:
        try:
            dt_timestamp = datetime.fromtimestamp(int(timestamp))
        except (ValueError, TypeError) as e:
            _logger.warning(f"Invalid timestamp {timestamp}: {e}")
    
    try:
        media_info = get_url(id, timestamp=dt_timestamp)
        
        if not media_info:
            raise HTTPException(
                status_code=404,
                detail=f"Media not found for ID: {id}"
            )
        
        # Check if error was returned
        if "error" in media_info:
            _logger.warning(f"Media fetch returned error for {id}: {media_info['error']}")
            raise HTTPException(
                status_code=404,
                detail=media_info["error"]
            )
        
        _logger.info(f"Successfully retrieved media info for {id}")
        
        # Log statistics periodically
        stats = cache.get_statistics()
        if stats.get("total_requests", 0) % 10 == 0:  # Every 10 requests
            cache.log_statistics()
        
        return JSONResponse(content=media_info, status_code=200)
    
    except HTTPException:
        raise
    except Exception as e:
        _logger.error(f"Failed to fetch media {id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch media: {str(e)}"
        )