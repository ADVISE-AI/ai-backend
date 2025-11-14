"""
Media Cache Statistics Endpoint
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from config import logger
from utility.media_cache_manager import get_media_cache

router = APIRouter()
_logger = logger(__name__)


@router.get("/media/stats")
async def get_media_stats():
    """
    Get media cache statistics
    
    Returns:
        JSON response with cache statistics including:
        - total_requests: Total media fetch requests
        - cache_hits: Number of cache hits (local + failed cache)
        - api_calls: Number of actual API calls made
        - failed_calls: Number of failed API calls
        - expired_media: Number of expired media (>24 hours)
        - cache_hit_rate: Percentage of cache hits
    """
    try:
        cache = get_media_cache()
        stats = cache.get_statistics()
        
        _logger.info(f"Media cache statistics requested: {stats}")
        
        return JSONResponse(content={
            "status": "success",
            "statistics": stats
        }, status_code=200)
    
    except Exception as e:
        _logger.error(f"Failed to get media statistics: {e}", exc_info=True)
        return JSONResponse(content={
            "status": "error",
            "message": str(e)
        }, status_code=500)


@router.post("/media/cleanup")
async def cleanup_old_media():
    """
    Manually trigger cleanup of old cached media files
    
    Removes media files older than 7 days from local storage
    """
    try:
        cache = get_media_cache()
        cache.cleanup_old_media()
        
        _logger.info("Manual media cleanup triggered")
        
        return JSONResponse(content={
            "status": "success",
            "message": "Old media cleanup completed"
        }, status_code=200)
    
    except Exception as e:
        _logger.error(f"Failed to cleanup old media: {e}", exc_info=True)
        return JSONResponse(content={
            "status": "error",
            "message": str(e)
        }, status_code=500)
