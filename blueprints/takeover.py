from flask import Blueprint, request, jsonify
from config import logger
from db import engine, conversation
from sqlalchemy import select, update
from bot import graph

takeover_bp = Blueprint('takeover', __name__)
_logger = logger(__name__)

@takeover_bp.route("/takeover", methods=["POST"])  
def takeover_by_human():
    """Takeover conversation by human agent"""
    data = request.get_json()
    
    if not data or "phone" not in data:
        return jsonify({"status": "error", "message": "Missing phone"}), 400

    phone = data["phone"]

    try:
        with engine.begin() as conn:
            # Set intervention flag
            conn.execute(
                update(conversation)
                .where(conversation.c.phone == str(phone))
                .values({"human_intervention_required": True})
            )
            
            # Update LangGraph state
            config = {"configurable": {"thread_id": phone}}
            graph.update_state(config, {"operator_active": True})
            
        return jsonify({"status": "takeover_complete"})
        
    except Exception as e:
        _logger.error(f"Takeover failed: {e}")
        return jsonify({"status": "error"}), 500