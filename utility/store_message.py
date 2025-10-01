from config import logger
from db import engine, message, conversation
from sqlalchemy import insert, select
from bot import graph
from datetime import datetime
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
            # Reuse existing connection/transaction
            conn.execute(insert(message).values(row))
        else:
            # Create new transaction
            with engine.begin() as conn:
                conn.execute(insert(message).values(row))
    except Exception as e:
        _logger.error(f"Failed to insert into DataBase: {e}")

def store_operator_message(message_text: str, user_ph: str, external_msg_id: str = None, **kwargs):
    """Store operator message and sync to LangGraph
        Args:
            message_text: Text content of the operator message
            user_ph: Phone number of the user
            external_msg_id: Message ID returned by WhatsApp API
            `**kwargs`: Additional keyword arguments
        
            NOTE: `**kwargs` can include `media_id` and `mime_type` for media messages
            
        Returns: `None` """

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
        
        # CRITICAL: Sync to LangGraph state
        sync_operator_message_to_graph(user_ph, message_text)

def sync_operator_message_to_graph(user_ph: str, message_text: str):
    """Add operator message to LangGraph conversation state"""
    config = {"configurable": {"thread_id": user_ph}}
    
    # Create operator message in LangGraph format
    operator_message = {
        "role": "assistant", 
        "content": f"[OPERATOR MESSAGE]: {message_text}"
    }
    
    # Update the graph state directly
    current_state = graph.get_state(config)
    updated_messages = current_state.values.get("messages", []) + [operator_message]
    
    graph.update_state(config, {"messages": updated_messages})