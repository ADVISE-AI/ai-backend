import redis
import json
import time
from typing import List, Dict, Optional
from config import REDIS_URI, logger

_logger = logger(__name__)

_message_buffer_instance = None

class Message_Buffer:
    """
    Redis-based message buffer with debouncing to handle rapid-fire messages.
    Thread-safe through Redis atomic operations.
    """
    
    def __init__(self, debounce_time: float = 2.0, max_wait_time: float = 20.0):
        """
        Initialize message buffer
        
        Args:
            debounce_time: Seconds to wait after last message before processing (default: 2s)
            max_wait_time: Maximum time to buffer messages before force-processing (default: 20s)
        """
        try:
            self.redis_client = redis.from_url(REDIS_URI, decode_responses=True)
            # Test connection
            self.redis_client.ping()
            _logger.info("Message buffer Redis connection established")
        except Exception as e:
            _logger.error(f"Failed to connect to Redis for message buffer: {e}")
            raise
            
        self.debounce_time = debounce_time
        self.max_wait_time = max_wait_time
        
        # Lua script for atomic get-and-delete
        self.get_and_delete_script = self.redis_client.register_script("""
            local buffer_key = KEYS[1]
            local timer_key = KEYS[2]
            
            local messages = redis.call('LRANGE', buffer_key, 0, -1)
            
            if #messages > 0 then
                redis.call('DEL', buffer_key)
                redis.call('DEL', timer_key)
            end
            
            return messages
        """)
        
    def _get_buffer_key(self, phone: str) -> str:
        """Get Redis key for user's message buffer"""
        return f"msg_buffer:{phone}"
    
    def _get_timer_key(self, phone: str) -> str:
        """Get Redis key for user's timer"""
        return f"msg_buffer_timer:{phone}"
    
    def _get_first_msg_key(self, phone: str) -> str:
        """Get Redis key for first message timestamp"""
        return f"msg_buffer_first:{phone}"
    
    def add_message(self, phone: str, normalized_message: dict) -> bool:
        """
        Add message to buffer
        
        Args:
            phone: User's phone number
            normalized_message: Normalized message dict
            
        Returns:
            True if this is the first message (start buffering)
            False if adding to existing buffer
        """
        buffer_key = self._get_buffer_key(phone)
        timer_key = self._get_timer_key(phone)
        first_msg_key = self._get_first_msg_key(phone)
        
        try:
            # Use pipeline for atomicity
            pipe = self.redis_client.pipeline()
            
            # Check if buffer exists
            pipe.exists(buffer_key)
            
            # Add message to list
            pipe.rpush(buffer_key, json.dumps(normalized_message))
            
            # Set expiry (max_wait_time + buffer to prevent premature deletion)
            pipe.expire(buffer_key, int(self.max_wait_time) + 5)
            
            # Update last message timestamp
            pipe.set(timer_key, time.time(), ex=int(self.max_wait_time) + 5)
            
            # Set first message timestamp if not exists
            pipe.set(first_msg_key, time.time(), ex=int(self.max_wait_time) + 5, nx=True)
            
            # Get buffer size
            pipe.llen(buffer_key)
            
            results = pipe.execute()
            
            buffer_existed = results[0]  # First command result
            buffer_size = results[-1]     # Last command result
            
            if not buffer_existed:
                _logger.info(f"Started message buffer for {phone}")
                return True
            else:
                _logger.info(f"Added to buffer for {phone}. Total messages: {buffer_size}")
                return False
                
        except redis.RedisError as e:
            _logger.error(f"Redis error in add_message for {phone}: {e}")
            # Return True to trigger processing immediately on Redis failure
            return True
        except json.JSONEncodeError as e:
            _logger.error(f"Failed to serialize message for {phone}: {e}")
            return False
        except Exception as e:
            _logger.error(f"Unexpected error in add_message for {phone}: {e}")
            return True
    
    def should_process(self, phone: str) -> bool:
        """
        Check if enough time has passed to process messages
        
        Args:
            phone: User's phone number
            
        Returns:
            True if messages should be processed now
        """
        timer_key = self._get_timer_key(phone)
        first_msg_key = self._get_first_msg_key(phone)
        
        try:
            last_message_time = self.redis_client.get(timer_key)
            first_message_time = self.redis_client.get(first_msg_key)
            
            if not last_message_time:
                _logger.warning(f"No timer found for {phone}, assuming should process")
                return True
            
            current_time = time.time()
            time_since_last = current_time - float(last_message_time)
            
            # Check if debounce time has passed
            if time_since_last >= self.debounce_time:
                _logger.info(f"Debounce time reached for {phone} ({time_since_last:.1f}s)")
                return True
            
            # Check if max wait time exceeded
            if first_message_time:
                time_since_first = current_time - float(first_message_time)
                if time_since_first >= self.max_wait_time:
                    _logger.warning(f"Max wait time exceeded for {phone} ({time_since_first:.1f}s)")
                    return True
            
            _logger.info(f"Still buffering for {phone} (last: {time_since_last:.1f}s ago)")
            return False
            
        except ValueError as e:
            _logger.error(f"Invalid timestamp in Redis for {phone}: {e}")
            return True  # Process on error
        except redis.RedisError as e:
            _logger.error(f"Redis error in should_process for {phone}: {e}")
            return True  # Process on error
        except Exception as e:
            _logger.error(f"Unexpected error in should_process for {phone}: {e}")
            return True
    
    def get_messages(self, phone: str) -> Optional[List[dict]]:
        """
        Get all buffered messages for a user and atomically clear the buffer
        
        Args:
            phone: User's phone number
            
        Returns:
            List of messages or None if buffer is empty
        """
        buffer_key = self._get_buffer_key(phone)
        timer_key = self._get_timer_key(phone)
        first_msg_key = self._get_first_msg_key(phone)
        
        try:
            # Use Lua script for atomic get-and-delete
            messages_json = self.get_and_delete_script(
                keys=[buffer_key, timer_key],
                args=[]
            )
            
            # Also delete first message timestamp
            self.redis_client.delete(first_msg_key)
            
            if not messages_json:
                _logger.info(f"No messages in buffer for {phone}")
                return None
            
            # Parse messages
            messages = []
            for msg_json in messages_json:
                try:
                    messages.append(json.loads(msg_json))
                except json.JSONDecodeError as e:
                    _logger.error(f"Failed to parse buffered message for {phone}: {e}")
                    continue
            
            if messages:
                _logger.info(f"Retrieved {len(messages)} messages for {phone}")
                return messages
            else:
                _logger.warning(f"All messages failed to parse for {phone}")
                return None
                
        except redis.RedisError as e:
            _logger.error(f"Redis error in get_messages for {phone}: {e}")
            return None
        except Exception as e:
            _logger.error(f"Unexpected error in get_messages for {phone}: {e}")
            return None
    
    def get_buffer_size(self, phone: str) -> int:
        """
        Get current buffer size for a user
        
        Args:
            phone: User's phone number
            
        Returns:
            Number of messages in buffer
        """
        buffer_key = self._get_buffer_key(phone)
        try:
            return self.redis_client.llen(buffer_key)
        except redis.RedisError as e:
            _logger.error(f"Redis error getting buffer size for {phone}: {e}")
            return 0
    
    def clear_buffer(self, phone: str) -> bool:
        """
        Manually clear buffer for a user (useful for testing/debugging)
        
        Args:
            phone: User's phone number
            
        Returns:
            True if buffer was cleared
        """
        buffer_key = self._get_buffer_key(phone)
        timer_key = self._get_timer_key(phone)
        first_msg_key = self._get_first_msg_key(phone)
        
        try:
            pipe = self.redis_client.pipeline()
            pipe.delete(buffer_key)
            pipe.delete(timer_key)
            pipe.delete(first_msg_key)
            pipe.execute()
            
            _logger.info(f"Manually cleared buffer for {phone}")
            return True
        except redis.RedisError as e:
            _logger.error(f"Failed to clear buffer for {phone}: {e}")
            return False
    
    def get_buffer_stats(self) -> dict:
        """
        Get statistics about all active buffers
        
        Returns:
            Dict with buffer statistics
        """
        try:
            buffer_keys = self.redis_client.keys("msg_buffer:*")
            # Filter out timer and first_msg keys
            buffer_keys = [k for k in buffer_keys if not k.endswith("_timer") and not k.endswith("_first")]
            
            active_buffers = len(buffer_keys)
            
            stats = {
                "active_buffers": active_buffers,
                "debounce_time": self.debounce_time,
                "max_wait_time": self.max_wait_time,
                "status": "healthy"
            }
            
            # Get size of each buffer
            if active_buffers > 0 and active_buffers < 100:  # Only if reasonable number
                buffer_sizes = {}
                for key in buffer_keys:
                    phone = key.replace("msg_buffer:", "")
                    buffer_sizes[phone] = self.redis_client.llen(key)
                stats["buffer_sizes"] = buffer_sizes
            
            return stats
            
        except redis.RedisError as e:
            return {
                "status": "error",
                "error": str(e)
            }

def get_message_buffer() -> Message_Buffer:
    """
    Get or create global Redis buffer instance (Singleton pattern)
    
    Returns:
        Message_Buffer instance
    """
    global _message_buffer_instance 
    if _message_buffer_instance is None:
        # Use 2 seconds to match webhook countdown
        _message_buffer_instance = Message_Buffer(debounce_time=0.5, max_wait_time=10.0)
        _logger.info("Created new message buffer instance")
    return _message_buffer_instance