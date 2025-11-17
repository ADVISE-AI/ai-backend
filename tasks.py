from celery import Celery
from celery.signals import task_failure, task_success
from config import logger, REDIS_URI
from utility import message_router
from utility.message_buffer import get_message_buffer
from db import engine, message as message_table
from sqlalchemy import update
import bot

_logger = logger(__name__)

celery_app = Celery("webhook", broker=REDIS_URI, backend=REDIS_URI)

celery_app.conf.update(
    # Serialization
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    result_expires=3600,  
    
    # Timezone
    timezone='Asia/Kolkata',  
    enable_utc=True,
    
    # Task execution
    task_track_started=True,
    task_time_limit=300,
    task_soft_time_limit=240,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    
    # Reliability
    task_reject_on_worker_lost=True,
    task_acks_on_failure_or_timeout=True,
    
    # Performance
    worker_max_tasks_per_child=100,
    worker_disable_rate_limits=True,
    
    # Monitoring
    worker_send_task_events=True,
    task_send_sent_event=True,
)

@celery_app.task(
    name='tasks.update_langgraph_state',
    bind=True,
    max_retries=3,
    default_retry_delay=5,
    autoretry_for=(Exception,),
    retry_backoff=True
)
def update_langgraph_state_task(self, phone: str, updates: dict):
    """
    Update LangGraph state in background (prevents blocking Gunicorn workers)
    
    Args:
        phone: User phone number (thread_id)
        updates: Dict of state updates (e.g., {"operator_active": True})
    
    Returns:
        dict: Success/failure status
    """
    try:
        _logger.info(f"[Celery-{self.request.id[:8]}] Updating LangGraph state for {phone}")
        
        config = {"configurable": {"thread_id": phone}}
        graph = bot.get_graph()
        
        # Update state
        graph.update_state(config, updates)
        
        _logger.info(f"[Celery-{self.request.id[:8]}] LangGraph state updated for {phone}")
        return {"status": "success", "phone": phone, "updates": updates}
        
    except Exception as e:
        _logger.error(f"[Celery-{self.request.id[:8]}] LangGraph update failed for {phone}: {e}", exc_info=True)
        raise


@celery_app.task(
    name='tasks.sync_operator_message_to_graph',
    bind=True,
    max_retries=3,
    default_retry_delay=5
)
def sync_operator_message_to_graph_task(self, phone: str, message_text: str):
    """
    Sync operator message to LangGraph conversation state
    
    Args:
        phone: User phone number
        message_text: Operator's message content
    """
    try:
        _logger.info(f"[Celery-{self.request.id[:8]}] Syncing operator message to graph for {phone}")
        
        config = {"configurable": {"thread_id": phone}}
        graph = bot.get_graph()
        
        # Get current state
        current_state = graph.get_state(config)
        
        # Add operator message
        operator_message = {
            "role": "assistant", 
            "content": f"[OPERATOR MESSAGE]: {message_text}"
        }
        
        updated_messages = current_state.values.get("messages", []) + [operator_message]
        graph.update_state(config, {"messages": updated_messages})
        
        _logger.info(f"[Celery-{self.request.id[:8]}] Operator message synced to graph for {phone}")
        return {"status": "success", "phone": phone}
        
    except Exception as e:
        _logger.error(f"[Celery-{self.request.id[:8]}] Operator message sync failed for {phone}: {e}", exc_info=True)
        raise

@celery_app.task(name='tasks.check_buffer')
def check_buffer_task(phone: str):
    """Check if buffer should be processed for a user"""
    redis_buffer = get_message_buffer()
    
    _logger.info(f"Checking buffer for {phone}")
    
    if redis_buffer.should_process(phone):
        messages = redis_buffer.get_messages(phone)
        
        if messages:
            _logger.info(f"Processing {len(messages)} buffered messages for {phone}")
            combined_message = _combine_messages(messages)
            
            process_message_task.apply_async(
                args=[combined_message],
                queue='messages',
                priority=5
            )
        else:
            _logger.warning(f"No messages in buffer for {phone}")
    else:
        buffer_size = redis_buffer.get_buffer_size(phone)
        _logger.info(f"User {phone} still typing. Buffer size: {buffer_size}. Checking again in 1s")
        
        check_buffer_task.apply_async(
            args=[phone],
            countdown=1,
            queue='messages',
            priority=5
        )


def _combine_messages(messages: list) -> dict:
    """Combine multiple messages into a single normalized message"""
    if len(messages) == 1:
        return messages[0]
    
    first_msg = messages[0]
    last_msg = messages[-1]
    
    text_messages = [m for m in messages if m.get('class') == 'text']
    media_messages = [m for m in messages if m.get('class') == 'media']
    
    if text_messages and not media_messages:
        combined_text = "\n".join([
            m['from']['message'] 
            for m in text_messages 
            if m['from'].get('message')
        ])
        
        return {
            'class': 'text',
            'category': None,
            'type': first_msg['type'],
            'timestamp': last_msg['timestamp'],
            'from': {
                'phone': first_msg['from']['phone'],
                'name': first_msg['from']['name'],
                'message_id': last_msg['from']['message_id'],
                'message': combined_text,
            },
            'context': last_msg.get('context')
        }
    
    elif media_messages:
        last_media = media_messages[-1]
        
        all_text = []
        for m in text_messages:
            if m['from'].get('message'):
                all_text.append(m['from']['message'])
        for m in media_messages:
            if m['from'].get('message'):
                all_text.append(m['from']['message'])
        
        combined_caption = '\n'.join(all_text) if all_text else None
        
        return {
            'class': 'media',
            'category': last_media['category'],
            'type': last_media['type'],
            'timestamp': last_media['timestamp'],
            'from': {
                'phone': last_media['from']['phone'],
                'name': last_media['from']['name'],
                'message_id': last_media['from']['message_id'],
                'mime_type': last_media['from']['mime_type'],
                'media_id': last_media['from']['media_id'],
                'message': combined_caption
            },
            'context': last_media.get('context')
        }
    
    return last_msg


@celery_app.task(
    bind=True, 
    name='tasks.process_message',
    max_retries=3,
    default_retry_delay=10,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True
)
def process_message_task(self, normalized_data: dict):
    """Background task to process incoming WhatsApp message with AI"""
    phone = normalized_data['from']['phone']
    msg_id = normalized_data['from']['message_id']
    
    try:
        _logger.info(f"[Celery-{self.request.id[:8]}] Processing {msg_id} from {phone}")
        
        message_router(normalized_data)
        
        _logger.info(f"[Celery-{self.request.id[:8]}] Completed {msg_id}")
        
        return {
            "status": "success",
            "phone": phone,
            "message_id": msg_id,
            "task_id": self.request.id
        }
        
    except Exception as e:
        _logger.error(f"[Celery-{self.request.id[:8]}] Failed {msg_id}: {e}", exc_info=True)
        raise


@celery_app.task(name='tasks.update_message_status')
def update_message_status_task(status_data: dict):
    """Update message delivery status from WhatsApp webhook"""
    try:
        msg_id = status_data.get('id')
        status = status_data.get('status')
        
        if not msg_id or not status:
            _logger.warning(f"Invalid status data: {status_data}")
            return {"status": "skipped", "reason": "missing_data"}
        
        _logger.info(f"Updating status for {msg_id}: {status}")
        
        with engine.begin() as conn:
            result = conn.execute(
                update(message_table)
                .where(message_table.c.external_id == msg_id)
                .values(status=status)
            )
            
            if result.rowcount > 0:
                _logger.info(f"Status updated: {msg_id} -> {status}")
            else:
                _logger.warning(f"️Message not found: {msg_id}")
        
        return {
            "status": "success",
            "message_id": msg_id,
            "new_status": status
        }
        
    except Exception as e:
        _logger.error(f"Status update failed: {e}", exc_info=True)
        return {"status": "failed", "error": str(e)}

@celery_app.task(
    name='tasks.process_operator_media',
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    autoretry_for=(Exception,),
    retry_backoff=True,
    time_limit=180,  # 3 minutes hard limit
    soft_time_limit=150  # 2.5 minutes soft limit
)
def process_operator_media_task(self, phone: str, media_file_id: str, mime_type: str, 
                                message_text: str, sender_id: str):
    """
    Download media from backend, upload to WhatsApp, and store message
    
    Args:
        phone: Recipient phone number
        media_file_id: File ID from the interface backend
        mime_type: MIME type of the media
        message_text: Caption/message text
        sender_id: Operator user ID
    
    Returns:
        dict: Status and message_id
    """
    from blueprints.operatormsg import download_operator_media, get_media_type_and_extension
    from utility.whatsapp import upload_media, send_media
    from utility.store_message import store_operator_message
    import os
    
    try:
        _logger.info(f"[Celery-{self.request.id[:8]}] Processing operator media for {phone}")
        
        # Download media from interface backend
        downloaded_content = download_operator_media(media_file_id, mime_type)
        
        if not downloaded_content.get("success"):
            raise Exception(f"Media download failed: {downloaded_content.get('error')}")
        
        file_path = downloaded_content["file_path"]
        media_type = downloaded_content["media_type"]
        
        try:
            # Upload to WhatsApp
            media_id = upload_media(file_path)
            if not media_id:
                raise Exception("WhatsApp media upload failed")
            
            # Send to user
            response = send_media(media_type, phone, media_id, message_text)
            message_id = response.get("messages", [{}])[0].get('id') if response else None
            
            # Store in database
            store_operator_message(
                message_text, phone, message_id,
                media_id=media_id,
                mime_type=mime_type,
                sender_id=sender_id
            )
            
            _logger.info(f"[Celery-{self.request.id[:8]}] Operator media sent successfully")
            return {
                "status": "success",
                "message_id": message_id,
                "phone": phone
            }
            
        finally:
            # Clean up temp file
            if os.path.exists(file_path):
                os.remove(file_path)
                _logger.info(f"Cleaned up temp file: {file_path}")
                
    except Exception as e:
        _logger.error(f"[Celery-{self.request.id[:8]}] Operator media processing failed: {e}", 
                     exc_info=True)
        raise

# Task routing
celery_app.conf.task_routes = {
    'tasks.process_message': {
        'queue': 'messages',
        'routing_key': 'message.process',
    },
    'tasks.update_message_status': {
        'queue': 'status',
        'routing_key': 'message.status',
    },
    'tasks.update_langgraph_state': {
        'queue': 'state',  
        'routing_key': 'state.update',
    },
    'tasks.sync_operator_message_to_graph': {
        'queue': 'state',
        'routing_key': 'state.sync',
    },
    'tasks.process_operator_media': {
        'queue': 'media', #New task to process operator end uploaded media
        'routing_key': 'media.process',
    }
}


# Monitoring hooks
@task_failure.connect
def task_failure_handler(sender=None, task_id=None, exception=None, **kwargs):
    """Log critical failures"""
    _logger.critical(f"🚨 Task {task_id} failed: {exception}")


@task_success.connect
def task_success_handler(sender=None, result=None, **kwargs):
    """Log successful completions"""
    if result and isinstance(result, dict) and result.get('status') == 'success':
        _logger.debug(f"✅ Task completed: {result.get('task_id', 'unknown')[:8]}")