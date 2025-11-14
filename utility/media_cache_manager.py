"""
Media Cache Manager for WhatsApp Media
Handles:
- Failed media ID caching (Redis)
- Local media file storage
- Media age validation (24-hour expiration)
- Fetch statistics
"""
import os
import redis
import hashlib
import time
from typing import Optional, Dict, Tuple
from datetime import datetime, timedelta
from pathlib import Path
from config import REDIS_URI, logger

_logger = logger(__name__)

# Media storage directory
MEDIA_STORAGE_DIR = Path("tmp/whatsapp_media")
MEDIA_CACHE_DAYS = 7  # Keep cached media for 7 days
MEDIA_EXPIRATION_HOURS = 24  # WhatsApp media expires after 24 hours
FAILED_MEDIA_TTL = 3600  # Cache failed media IDs for 1 hour


class MediaCacheManager:
    """
    Manages media caching with Redis for failed IDs and local filesystem for successful downloads
    """
    
    def __init__(self):
        """Initialize media cache manager"""
        try:
            self.redis_client = redis.from_url(REDIS_URI, decode_responses=True)
            self.redis_client.ping()
            _logger.info("MediaCacheManager: Redis connection established")
        except Exception as e:
            _logger.error(f"MediaCacheManager: Failed to connect to Redis: {e}")
            self.redis_client = None
        
        # Create media storage directory
        try:
            MEDIA_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
            _logger.info(f"MediaCacheManager: Storage directory ready at {MEDIA_STORAGE_DIR}")
        except Exception as e:
            _logger.error(f"MediaCacheManager: Failed to create storage directory: {e}")
        
        # Statistics keys
        self.stats_key = "media:stats"
        self._init_stats()
    
    def _init_stats(self):
        """Initialize statistics counters"""
        if not self.redis_client:
            return
        
        try:
            # Initialize counters if they don't exist
            if not self.redis_client.exists(self.stats_key):
                stats = {
                    "total_requests": 0,
                    "cache_hits": 0,
                    "api_calls": 0,
                    "failed_calls": 0,
                    "expired_media": 0
                }
                self.redis_client.hset(self.stats_key, mapping=stats)
        except Exception as e:
            _logger.warning(f"Failed to initialize stats: {e}")
    
    def is_media_failed(self, media_id: str) -> bool:
        """
        Check if media ID is in failed cache
        
        Args:
            media_id: WhatsApp media ID
            
        Returns:
            True if media is cached as failed, False otherwise
        """
        if not self.redis_client:
            return False
        
        try:
            key = f"failed_media:{media_id}"
            exists = self.redis_client.exists(key)
            
            if exists:
                _logger.info(f"Media {media_id} found in failed cache, skipping API call")
                self._increment_stat("cache_hits")
                return True
            
            return False
        except Exception as e:
            _logger.warning(f"Failed to check failed cache for {media_id}: {e}")
            return False
    
    def mark_media_failed(self, media_id: str, error_message: str = ""):
        """
        Mark media ID as failed in cache
        
        Args:
            media_id: WhatsApp media ID
            error_message: Optional error message
        """
        if not self.redis_client:
            return
        
        try:
            key = f"failed_media:{media_id}"
            value = {
                "timestamp": datetime.now().isoformat(),
                "error": error_message
            }
            
            self.redis_client.setex(
                key,
                FAILED_MEDIA_TTL,
                str(value)
            )
            
            _logger.info(f"Marked media {media_id} as failed (TTL: {FAILED_MEDIA_TTL}s)")
            self._increment_stat("failed_calls")
        except Exception as e:
            _logger.warning(f"Failed to mark media as failed {media_id}: {e}")
    
    def is_media_expired(self, timestamp: datetime) -> bool:
        """
        Check if media is older than 24 hours
        
        Args:
            timestamp: Message timestamp when media was received
            
        Returns:
            True if media is expired, False otherwise
        """
        if not timestamp:
            return False
        
        try:
            age = datetime.now() - timestamp
            is_expired = age > timedelta(hours=MEDIA_EXPIRATION_HOURS)
            
            if is_expired:
                _logger.warning(f"Media expired (age: {age.total_seconds()/3600:.1f} hours)")
                self._increment_stat("expired_media")
            
            return is_expired
        except Exception as e:
            _logger.warning(f"Failed to check media expiration: {e}")
            return False
    
    def get_local_media_path(self, media_id: str, mime_type: str = "") -> Path:
        """
        Generate local file path for media
        
        Args:
            media_id: WhatsApp media ID
            mime_type: MIME type to determine extension
            
        Returns:
            Path object for local storage
        """
        # Create hash for filename
        hash_obj = hashlib.sha256(media_id.encode())
        filename = f"{media_id}_{hash_obj.hexdigest()[:8]}"
        
        # Add extension based on MIME type
        if mime_type:
            ext = self._mime_to_extension(mime_type)
            filename = f"{filename}{ext}"
        
        return MEDIA_STORAGE_DIR / filename
    
    def _mime_to_extension(self, mime_type: str) -> str:
        """Convert MIME type to file extension"""
        mime_map = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "video/mp4": ".mp4",
            "video/3gpp": ".3gp",
            "audio/aac": ".aac",
            "audio/mp4": ".m4a",
            "audio/mpeg": ".mp3",
            "audio/ogg": ".ogg",
            "application/pdf": ".pdf",
        }
        return mime_map.get(mime_type, ".bin")
    
    def get_cached_media(self, media_id: str) -> Optional[Dict]:
        """
        Retrieve media from local cache
        
        Args:
            media_id: WhatsApp media ID
            
        Returns:
            Dict with media data if found, None otherwise
        """
        try:
            # Find file with matching media_id prefix
            matching_files = list(MEDIA_STORAGE_DIR.glob(f"{media_id}_*"))
            
            if not matching_files:
                return None
            
            file_path = matching_files[0]
            
            # Check if file is too old (cleanup)
            file_age = datetime.now() - datetime.fromtimestamp(file_path.stat().st_mtime)
            if file_age > timedelta(days=MEDIA_CACHE_DAYS):
                _logger.info(f"Removing old cached media: {file_path.name}")
                file_path.unlink()
                return None
            
            # Read file
            with open(file_path, "rb") as f:
                data = f.read()
            
            # Determine MIME type from extension
            ext = file_path.suffix
            mime_type = self._extension_to_mime(ext)
            
            _logger.info(f"Retrieved media {media_id} from local cache")
            self._increment_stat("cache_hits")
            
            return {
                "content_type": mime_type,
                "data": data,
                "mime_type": mime_type,
                "cached": True
            }
        except Exception as e:
            _logger.warning(f"Failed to retrieve cached media {media_id}: {e}")
            return None
    
    def _extension_to_mime(self, ext: str) -> str:
        """Convert file extension to MIME type"""
        ext_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".mp4": "video/mp4",
            ".3gp": "video/3gpp",
            ".aac": "audio/aac",
            ".m4a": "audio/mp4",
            ".mp3": "audio/mpeg",
            ".ogg": "audio/ogg",
            ".pdf": "application/pdf",
        }
        return ext_map.get(ext.lower(), "application/octet-stream")
    
    def save_media_to_cache(self, media_id: str, data: bytes, mime_type: str) -> bool:
        """
        Save media to local cache
        
        Args:
            media_id: WhatsApp media ID
            data: Media binary data
            mime_type: MIME type
            
        Returns:
            True if saved successfully, False otherwise
        """
        try:
            file_path = self.get_local_media_path(media_id, mime_type)
            
            with open(file_path, "wb") as f:
                f.write(data)
            
            _logger.info(f"Saved media {media_id} to local cache ({len(data)} bytes)")
            return True
        except Exception as e:
            _logger.error(f"Failed to save media {media_id} to cache: {e}")
            return False
    
    def cleanup_old_media(self):
        """Remove media files older than MEDIA_CACHE_DAYS"""
        try:
            cutoff_time = datetime.now() - timedelta(days=MEDIA_CACHE_DAYS)
            removed_count = 0
            
            for file_path in MEDIA_STORAGE_DIR.glob("*"):
                if file_path.is_file():
                    file_time = datetime.fromtimestamp(file_path.stat().st_mtime)
                    if file_time < cutoff_time:
                        file_path.unlink()
                        removed_count += 1
            
            if removed_count > 0:
                _logger.info(f"Cleaned up {removed_count} old media files")
        except Exception as e:
            _logger.error(f"Failed to cleanup old media: {e}")
    
    def _increment_stat(self, stat_name: str):
        """Increment a statistics counter"""
        if not self.redis_client:
            return
        
        try:
            self.redis_client.hincrby(self.stats_key, stat_name, 1)
        except Exception as e:
            _logger.warning(f"Failed to increment stat {stat_name}: {e}")
    
    def get_statistics(self) -> Dict:
        """
        Get media fetch statistics
        
        Returns:
            Dict with statistics
        """
        if not self.redis_client:
            return {}
        
        try:
            stats = self.redis_client.hgetall(self.stats_key)
            
            # Convert to integers
            stats = {k: int(v) for k, v in stats.items()}
            
            # Calculate derived metrics
            total = stats.get("total_requests", 0)
            cache_hits = stats.get("cache_hits", 0)
            
            if total > 0:
                stats["cache_hit_rate"] = f"{(cache_hits / total * 100):.1f}%"
            else:
                stats["cache_hit_rate"] = "0%"
            
            return stats
        except Exception as e:
            _logger.error(f"Failed to get statistics: {e}")
            return {}
    
    def log_statistics(self):
        """Log current statistics"""
        stats = self.get_statistics()
        if stats:
            _logger.info(f"📊 Media Cache Statistics: {stats}")


# Global instance
_media_cache_instance = None

def get_media_cache() -> MediaCacheManager:
    """Get or create global MediaCacheManager instance"""
    global _media_cache_instance
    
    if _media_cache_instance is None:
        _media_cache_instance = MediaCacheManager()
    
    return _media_cache_instance
