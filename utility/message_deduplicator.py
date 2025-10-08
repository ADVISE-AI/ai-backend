import redis
from config import REDIS_URI, logger

_logger = logger(__name__)

message_cache = {}
CACHE_DURATION = 120

_logger.info("Establishing Redis connection")

redis_client = redis.from_url(REDIS_URI, decode_responses = True)

if redis_client.ping():
    _logger.info("Redis connection established")
else:
    _logger.error("Redis ping failed")


def is_duplicate(wa_message_id: str, user_phone: str) -> bool:

    cache_key = f"msg_dedup:{user_phone}:{wa_message_id}"

    try:
        set_new_message = redis_client.set(cache_key, "1", nx=True, ex=CACHE_DURATION)

        if set_new_message:
            _logger.info(f" New message: {cache_key}")
            return False
    
        else:
            _logger.info(f" Duplicate message: {cache_key}")
            return True
    except Exception as e:
        _logger.error("Deduplication failed: {e}")


def get_dedup_stats():
    try:
        keys = redis_client.keys("msg_dedup:*")
        return {
            "backend": "redis",
            "total_entries": len(keys) if keys else 0,
            "cache_duration": CACHE_DURATION,
            "status": "healthy"
        }
    except Exception as e:
        return {
            "backend": "redis",
            "status": "error",
            "error": str(e)
        }

    