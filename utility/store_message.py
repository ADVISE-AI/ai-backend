from config import logger
from db import engine, message, conversation
from sqlalchemy import insert, select
from datetime import datetime
from tasks import sync_operator_message_to_graph_task
import json
import time

_logger = logger(__name__)

def store_user_message(clean_data: dict, conversation_id: int, conn=None):
    """Store user message without AI processing
    
    Args:
        clean_data: Normalized message data
        conversation_id: ID of the conversation
        conn: Optional database connection (for reusing transaction)
    """
    
    row = {
        "conversation_id": conversation_id,
        "direction": "inbound",
        "sender_type": "customer", 
        "external_id": str(clean_data['from'].get('message_id')),
        "has_text": True if clean_data['from'].get('message') else False,
        "message_text": clean_data['from'].get('message') if isinstance(clean_data['from'].get('message'), str) else None,

        "media_info": json.dumps({
                "id": clean_data['from'].get('media_id'),
                "mime_type": clean_data['from'].get('mime_type'),
                "description": ""
            }) if clean_data['from'].get('media_id') or clean_data['from'].get('mime_type') else None,

        "provider_ts": datetime.fromtimestamp(int(time.time())),
        "extra_metadata": json.dumps({"context": clean_data.get("context")}) if clean_data.get("context") else None
    }

    try:
        if conn:
            conn.execute(insert(message).values(row))
        else:
            with engine.begin() as conn:
                conn.execute(insert(message).values(row))
    except Exception as e:
        _logger.error(f"Failed to insert into DataBase: {e}")


def store_operator_message(message_text: str, user_ph: str, external_msg_id: str = None, **kwargs):
    """
    Store operator message and sync to LangGraph (async via Celery)
    
    Args:
        message_text: Text content of the operator message
        user_ph: Phone number of the user
        external_msg_id: Message ID returned by WhatsApp API
        **kwargs: Additional keyword arguments (media_id, mime_type, sender_id)
        
    Returns: None
    
    CRITICAL FIX: Graph sync now happens asynchronously via Celery task.
    This prevents blocking the Gunicorn worker on LangGraph state updates.
    """
    with engine.begin() as conn:
        # Get conversation
        result = conn.execute(
            select(conversation.c.id).where(conversation.c.phone == str(user_ph))
        )
        conversation_id = result.scalar_one()
        
        # Store in database
        row = {
            "conversation_id": conversation_id,
            "direction": "outbound",
            "sender_type": "operator",
            "sender_id": kwargs.get("sender_id"),
            "external_id": external_msg_id,
            "has_text": True,
            "media_info": json.dumps({
                    "id": kwargs.get("media_id"),
                    "mime_type": kwargs.get("mime_type"),
                    "description": ""
                }) if kwargs.get("media_id") or kwargs.get("mime_type") else None,
            "message_text": message_text,
            "provider_ts": datetime.fromtimestamp(int(time.time())),
        }
        conn.execute(insert(message).values(row))
        _logger.info(f"Operator message stored in DB for {user_ph}")
    
    # CRITICAL FIX: Offload graph sync to Celery
    # This prevents blocking on LangGraph state updates
    sync_operator_message_to_graph_task.apply_async(
        args=[user_ph, message_text],
        queue='state',
        priority=7  # High priority (but lower than takeover/handback)
    )
    _logger.info(f"Queued operator message sync to graph for {user_ph}")


def sync_operator_message_to_graph(user_ph: str, message_text: str):
    """
    DEPRECATED: Use sync_operator_message_to_graph_task instead
    
    This function is kept for backward compatibility but should not be called directly.
    All graph syncs now go through Celery to prevent blocking.
    
    If called directly, it will queue the Celery task instead.
    """
    _logger.warning(
        "sync_operator_message_to_graph() called directly - "
        "this is deprecated. Use Celery task instead. Queuing task now..."
    )
    sync_operator_message_to_graph_task.apply_async(
        args=[user_ph, message_text],
        queue='state',
        priority=7
    )