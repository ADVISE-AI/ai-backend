import redis
from config import REDIS_URI, logger
import time
from functools import wraps

_logger = logger(__name__)

message_cache = {}
CACHE_DURATION = 120
redis_client = None

# Initialize Redis connection
try:
    if REDIS_URI:
        _logger.info(f"Connecting to Redis at {REDIS_URI.split('@')[-1] if '@' in REDIS_URI else REDIS_URI}")
        redis_client = redis.Redis.from_url(REDIS_URI, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
        redis_client.ping()  # Test the connection
        _logger.info("✅ Redis connection established")
    else:
        _logger.warning("REDIS_URI not set, using in-memory cache only")
except Exception as e:
    _logger.warning(f"⚠️ Could not connect to Redis: {e}. Using in-memory cache only")
    redis_client = None

def with_redis_fallback(func):
    """Decorator to fall back to in-memory cache if Redis is not available"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if redis_client is not None:
            try:
                return func(*args, **kwargs)
            except redis.RedisError as e:
                _logger.warning(f"Redis operation failed: {e}, falling back to in-memory cache")
        # Fallback to in-memory cache
        return func(*args, _use_redis=False, **kwargs)
    return wrapper

@with_redis_fallback
def is_duplicate(wa_message_id: str, user_phone: str, _use_redis: bool = True) -> bool:
    """Check if a message is a duplicate"""
    if _use_redis and redis_client:
        try:
            cache_key = f"msg:{user_phone}:{wa_message_id}"
            if redis_client.exists(cache_key):
                return True
            redis_client.setex(cache_key, CACHE_DURATION, "1")
            return False
        except redis.RedisError as e:
            _logger.warning(f"Redis operation failed: {e}")
    
    # Fallback to in-memory cache
    cache_key = f"{user_phone}:{wa_message_id}"
    current_time = time.time()
    
    # Clean up old entries
    global message_cache
    message_cache = {k: v for k, v in message_cache.items() if v > current_time}
    
    if cache_key in message_cache:
        return True
        
    message_cache[cache_key] = current_time + CACHE_DURATION
    return False

def get_dedup_stats():
    """Get deduplication statistics"""
    stats = {
        "cache_type": "redis" if redis_client else "in_memory",
        "status": "connected" if redis_client else "redis_unavailable"
    }
    
    if redis_client:
        try:
            stats["keys_count"] = redis_client.dbsize()
            stats["info"] = redis_client.info()
        except redis.RedisError as e:
            stats["status"] = f"error: {str(e)[:100]}"
            stats["keys_count"] = "unavailable"
    else:
        stats["keys_count"] = len(message_cache)
    
    return stats