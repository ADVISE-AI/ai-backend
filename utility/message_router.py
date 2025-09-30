from config import logger
from db import engine, conversation
from sqlalchemy import select, insert
from .store_message import store_user_message
from .handle_with_ai import handle_with_ai


_logger = logger(__name__)

def message_router(clean_data: dict):
    """Route message to AI or store directly based on conversation state
    1. Check if conversation exists
    2. If not, create new conversation, store message, process with AI
    3. If exists, check if human intervention is requested
        a. If yes, store message and notify operator
        b. If no, store message and process with AI
    
    Args:
        clean_data: Cleaned incoming message data
    
    Returns:
        str: Status message
        int: HTTP status code
    """


    try: 
        with engine.begin() as conn:
            result_obj = conn.execute(select(conversation.c.id, conversation.c.human_intervention_required).where(conversation.c.phone == f"{clean_data['from']['phone']}"))
            row = result_obj.mappings().first()

            if not row:
                # New conversation
                result = conn.execute(insert(conversation).values({"phone": clean_data["from"]["phone"], "name": clean_data["from"]["name"]}).returning(conversation.c.id))
                conversation_id = result.scalar_one()

                store_user_message(clean_data, conversation_id)
                handle_with_ai(clean_data, conversation_id)
                return "New conversation started and processed with AI", 200

            elif row:
                conversation_id = row["id"]
                interrupt_required = row["human_intervention_required"]

                if interrupt_required:
                    store_user_message(clean_data, conversation_id)
                    return "Operator intervention required", 200
                else:
                    store_user_message(clean_data, conversation_id)
                    handle_with_ai(clean_data, conversation_id)
                    return "Message processed with AI", 200
        return

    except Exception as e:
        _logger.error(f"Database error: {e}")
        return
