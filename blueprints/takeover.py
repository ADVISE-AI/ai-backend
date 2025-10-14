from flask import Blueprint, request, jsonify
from config import logger
from db import engine, conversation
from sqlalchemy import select, update
import bot
import json
takeover_bp = Blueprint('takeover', __name__)
_logger = logger(__name__)

@takeover_bp.route("/takeover", methods=["GET", "POST"])  
def takeover_by_human():
    """Takeover conversation by human agent"""
    if request.method=="POST":
        data = request.get_json(force=True)
        
        _logger.info(f"DATA RECEIVED: {json.dumps(data, indent = 2)}")


        if not data or "phone" not in data:
            return jsonify({"status": "error", "message": "Missing phone"}), 400

        phone = data["phone"]

        try:
            _logger.info(f"Setting intervention flag for {phone}")
            with engine.begin() as conn:
                # Set intervention flag
                conn.execute(
                    update(conversation)
                    .where(conversation.c.phone == str(phone))
                    .values({"human_intervention_required": True})
                )
                _logger.info(f"Intervention flag set for {phone}")
                
                # Update LangGraph state
                _logger.info(f"Updating LangGraph state for {phone}")
                config = {"configurable": {"thread_id": phone}}
                graph = bot.get_graph()
                graph.update_state(config, {"operator_active": True})
                _logger.info(f"LangGraph state updated for {phone}")
                
            return jsonify({"status": "takeover_complete"}), 200
            
        except Exception as e:
            _logger.error(f"Takeover failed: {e}")
            return jsonify({"status": "error"}), 500
        
    elif request.method == "GET":
        return "THIS ENDPOINT IS UP AND WORKS", 200