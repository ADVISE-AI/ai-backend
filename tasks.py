from celery import Celery
from celery.signals import task_failure, task_success
from config import logger, REDIS_URI
from utility import message_router
from db import engine, message as message_table
from sqlalchemy import update

_logger = logger(__name__)

celery_app = Celery("whatsapp_webhook", broker=REDIS_URI, backend=REDIS_URI)

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
    task_time_limit=300,  # 5 minutes hard limit
    task_soft_time_limit=240,  # 4 minutes soft limit
    task_acks_late=True,  # Acknowledge after task completes
    worker_prefetch_multiplier=1,  
    
    # Reliability
    task_reject_on_worker_lost=True,
    task_acks_on_failure_or_timeout=True,
    
    # Performance
    worker_max_tasks_per_child=100,  # Restart worker after 100 tasks
    worker_disable_rate_limits=True,
    
    # Monitoring
    worker_send_task_events=True,
    task_send_sent_event=True,
)


@celery_app.task(
    bind=True, 
    name='tasks.process_message',
    max_retries=3,
    default_retry_delay=10,  # Retry after 10 seconds
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True
)
def process_message_task(self, normalized_data: dict):
    """
    Background task to process incoming WhatsApp message with AI
    
    Args:
        normalized_data: Normalized webhook payload
        
    Returns:
        dict: Processing result with status
    """
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
    """
    Update message delivery status from WhatsApp webhook
    
    Args:
        status_data: Status update payload
    """
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


# Task routing to different queues
celery_app.conf.task_routes = {
    'tasks.process_message': {
        'queue': 'messages',
        'routing_key': 'message.process',
    },
    'tasks.update_message_status': {
        'queue': 'status',
        'routing_key': 'message.status',
    },
}


# Monitoring hooks
@task_failure.connect
def task_failure_handler(sender=None, task_id=None, exception=None, **kwargs):
    """Log critical failures"""
    _logger.critical(f"🚨 Task {task_id} failed: {exception}")
    # TODO: Send to monitoring system (Sentry, PagerDuty, etc.)


@task_success.connect
def task_success_handler(sender=None, result=None, **kwargs):
    """Log successful completions"""
    if result and isinstance(result, dict) and result.get('status') == 'success':
        _logger.debug(f"✅ Task completed: {result.get('task_id', 'unknown')[:8]}")