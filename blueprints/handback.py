from flask import Blueprint, request, jsonify
from config import logger
from db import engine, conversation
from sqlalchemy import select, update
from bot import graph

handback_bp = Blueprint('handback', __name__)
_logger = logger(__name__)

@handback_bp.route("/handback", methods=["POST"])  
def handback_to_ai():
    """Hand conversation back to AI"""
    data = request.get_json()
    phone = data["phone"]
    
    try:
        with engine.begin() as conn:
            # Clear intervention flag
            conn.execute(
                update(conversation)
                .where(conversation.c.phone == str(phone))
                .values(human_intervention_required=False)
            )
            
            # Update LangGraph state
            config = {"configurable": {"thread_id": phone}}
            graph.update_state(config, {"operator_active": False})
            
        return jsonify({"status": "handback_complete"})
        
    except Exception as e:
        _logger.error(f"Handback failed: {e}")
        return jsonify({"status": "error"}), 500