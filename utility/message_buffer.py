import time
import threading
from collections import defaultdict
from config import logger
from typing import Dict, List, Callable

_logger = logger(__name__)

_message_buffer_instance = None

class Message_Buffer:
    """ 
    Buffers messages then processes them in batches after the user stops typing.
    Uses debouncing: Waits for the silence before processing.
    """

    def __init__(self, 
                 debounce_time: float = 3.0, # Wait 3s after last message
                 max_wait_time: float = 10.0, # Max wait time before processing 
                 callback: Callable = None
                ):

        self.debounce_time = debounce_time
        self.max_wait_time = max_wait_time
        self.last_input_time = None
        self.processing_scheduled = False
        self.callback = callback
        
        # Store pending messages per user: {phone: {"messages": [], "timer": threading.Timer, "first_message_time": float} }
        self.buffers: Dict[str, dict] = defaultdict(lambda: {
            "messages": [],
            "metadata": {},
            "timer": None,
            "first_message_time": None
        })

        self.lock = threading.Lock()

    def add_message(self, phone: str, normalized_message: dict):
        """ Add a message to the buffer and schedule processing if needed. """
        with self.lock:
            buffer = self.buffers[phone]
            if not buffer["messages"]:
                buffer["first_message_time"] = time.time()
                _logger.info(f"Started message buffer for {phone}")
                buffer['metadata'] = {
                    "phone": normalized_message['from']['phone'],
                    "name": normalized_message['from']['name'],
                    "class": normalized_message["class"],
                    "timestamp": normalized_message["timestamp"]
                }
            buffer["messages"].append(normalized_message["from"]["message"])
            _logger.info(f"Buffered message for {phone}: {normalized_message['from']['message']}. Total buffered: {len(buffer['messages'])}")
    def _extract_message_content(self, normalized_message: dict)-> dict:
        if normalized_message["class"] == "text":
            return {
                'type': 'text',
                'content': normalized_message['from']['message'],
                'text': normalized_message['from']['message'],
                'context': normalized_message.get('context', None)
            }
        
        elif normalized_message['class'] == 'media':
            return {
                'type': normalized_message['category'],
                'media_id': normalized_message['from']['media_id'],
                'mime_type': normalized_message['from']['mime_type'],
                'caption': normalized_message['from']['message']
            }
        
        else:
            return {}
        
    def _combine_message(self, messages: List[dict], metadata: dict) -> dict:
        """ Reconstruct data format """
        if len(messages) == 1:
            return self._reconstruct_clean_data(messages[0], metadata)
        text_messages = [m for m in messages if m['type'] == 'text']
        media_messages = [m for m in messages if m['type'] == 'media']
        if text_messages and not media_messages:
            combined_text = "\n".join([m['text'] for m in text_messages])
            return {
                'class': 'text',
                'category': None,
                'type': metadata['type'],
                'timestamp': metadata['timestamp'],
                'from': {
                    'phone': metadata['phone'],
                    'name': metadata['name'],
                    'message_id': text_messages[-1]['message_id'],
                    'message': combined_text,
                },
                'context': text_messages[-1].get('context', None)
            }
        
        elif media_messages:
            last_media = media_messages[-1]
            all_text = []
            for m in text_messages:
                all_text.append(m['text'])
            for m in media_messages:
                if m.get('caption'):
                    all_text.append(m['caption'])
        
            combined_caption = '\n'.join(all_text) if all_text else None
            return {
                'class': 'media',
                'category': last_media['category'],
                'type': last_media['type'],
                'timestamp': last_media['timestamp'],
                'from': {
                    'phone': metadata['phone'],
                    'name': metadata['name'],
                    'message_id': last_media['from']['message_id'],
                    'mime_type': last_media['mime_type'],
                    'media_id': last_media['media_id'],
                    'message': combined_caption
                },
                'context': last_media.get('context', None)
            }
        return self._reconstruct_clean_data(messages[-1], metadata)
    
    def _reconstruct_clean_data(self, message: dict, metadata: dict) -> dict:
        """ Reconstruct data format """ 
        if message['type'] == 'text':
            return {
                'class': 'text',
                'category': None,
                'type': metadata['type'],
                'timestamp': metadata['timestamp'],
                'from': {
                    'phone': metadata['phone'],
                    'name': metadata['name'],
                    'message_id': message['message_id'],
                    'message': message['text'],
                },
                'context': message.get('context')
            }
        else:  # media
            return {
                'class': 'media',
                'category': message['category'],
                'type': metadata['type'],
                'timestamp': metadata['timestamp'],
                'from': {
                    'phone': metadata['phone'],
                    'name': metadata['name'],
                    'message_id': message['message_id'],
                    'mime_type': message['mime_type'],
                    'media_id': message['media_id'],
                    'message': message.get('caption')   
                },
                'context': message.get('context')
            }


def get_message_buffer(callback: Callable) -> Message_Buffer:
    """Get or create the global message buffer"""
    global _message_buffer_instance
    if _message_buffer_instance is None:
        _message_buffer_instance = Message_Buffer(
            debounce_time=3.0,  # Wait 3s after last message
            max_wait_time=10.0,  # But process after 10s max
            callback=callback
        )
    return _message_buffer_instance