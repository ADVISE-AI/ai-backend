import time

message_cache = {}
CACHE_DURATION = 30

def is_duplicate_message(msg_id, user_ph):
    """Check if message was already processed recently"""
    cache_key = f"{user_ph}_{msg_id}"
    current_time = time.time()
    
    if cache_key in message_cache:
        last_processed = message_cache[cache_key]
        if current_time - last_processed < CACHE_DURATION:
            return True
    
    message_cache[cache_key] = current_time
    
    # Clean old entries
    expired_keys = [k for k, v in message_cache.items() if current_time - v > CACHE_DURATION]
    for k in expired_keys:
        del message_cache[k]
    
    return False