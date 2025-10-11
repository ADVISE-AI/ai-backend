import redis
import json
import time
from typing import List, Dict, Optional
from config import REDIS_URI, logger

_logger = logger(__name__)

_message_buffer_instance = None

class Message_Buffer:
    
    def __init__(self, debounce_time: float = 10.0, max_wait_time: float = 20.0):
        self.redis_client = redis.from_url(REDIS_URI, decode_responses=True)
        self.debounce_time = debounce_time
        self.max_wait_time = max_wait_time
        
    def _get_buffer_key(self, phone: str) -> str:
        """Get Redis key for user's message buffer"""
        return f"msg_buffer:{phone}"
    
    def _get_timer_key(self, phone: str) -> str:
        """Get Redis key for user's timer"""
        return f"msg_buffer_timer:{phone}"
    
    def add_message(self, phone: str, normalized_message: dict) -> bool:
        """
        Add message to buffer
        
        Returns:
            True if this is the first message (start buffering)
            False if adding to existing buffer
        """
        buffer_key = self._get_buffer_key(phone)
        timer_key = self._get_timer_key(phone)
        
        # Check if buffer exists
        buffer_exists = self.redis_client.exists(buffer_key)
        
        # Add message to list
        self.redis_client.rpush(buffer_key, json.dumps(normalized_message))
        
        # Set expiry (max_wait_time)
        self.redis_client.expire(buffer_key, int(self.max_wait_time))
        
        # Update last message timestamp
        self.redis_client.set(timer_key, time.time(), ex=int(self.max_wait_time))
        
        if not buffer_exists:
            _logger.info(f"Started message buffer for {phone}")
            return True
        else:
            buffer_size = self.redis_client.llen(buffer_key)
            _logger.info(f"Added to buffer for {phone}. Total: {buffer_size}")
            return False
    
    def should_process(self, phone: str) -> bool:
        """
        Check if enough time has passed to process messages
        
        Returns:
            True if messages should be processed now
        """
        timer_key = self._get_timer_key(phone)
        
        last_message_time = self.redis_client.get(timer_key)
        if not last_message_time:
            return False
        
        time_since_last = time.time() - float(last_message_time)
        
        return time_since_last >= self.debounce_time
    
    def get_messages(self, phone: str) -> Optional[List[dict]]:
        """
        Get all buffered messages for a user and clear the buffer
        
        Returns:
            List of messages or None if buffer is empty
        """
        buffer_key = self._get_buffer_key(phone)
        timer_key = self._get_timer_key(phone)
        
        # Get all messages
        messages_json = self.redis_client.lrange(buffer_key, 0, -1)
        
        if not messages_json:
            return None
        
        # Parse messages
        messages = [json.loads(msg) for msg in messages_json]
        
        # Clear buffer
        self.redis_client.delete(buffer_key)
        self.redis_client.delete(timer_key)
        
        _logger.info(f"Retrieved {len(messages)} messages for {phone}")
        return messages
    
    def get_buffer_size(self, phone: str) -> int:
        """Get current buffer size for a user"""
        buffer_key = self._get_buffer_key(phone)
        return self.redis_client.llen(buffer_key)

def get_message_buffer() -> Message_Buffer:
    """Get or create global Redis buffer instance"""
    global _message_buffer_instance 
    if _message_buffer_instance is None:
        _message_buffer_instance = Message_Buffer(debounce_time=10.0, max_wait_time=20.0)
    return _message_buffer_instance 