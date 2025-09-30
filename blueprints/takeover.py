from flask import Blueprint, request, jsonify
from config import logger
from db import engine, conversation
from sqlalchemy import select, update
from bot import graph
import json
takeover_bp = Blueprint('takeover', __name__)
_logger = logger(__name__)

@takeover_bp.route("/takeover", methods=["GET", "POST"])  
def takeover_by_human():
    """Takeover conversation by human agent"""
    if request.method=="POST":
        data = request.get_json(force=True)
        
        _logger.info(f"DATA RECEIVED: {json.dumps(data, indent = 2)}")
        # print(f"DATA RECEIVED: {data}, {type(data)}")

        if data:
            return "OK", 200
        else:
            return "FAILED", 500
        # if not data or "phone" not in data:
        #     return jsonify({"status": "error", "message": "Missing phone"}), 400

        # phone = data["phone"]

        # try:
        #     with engine.begin() as conn:
        #         # Set intervention flag
        #         conn.execute(
        #             update(conversation)
        #             .where(conversation.c.phone == str(phone))
        #             .values({"human_intervention_required": True})
        #         )
                
        #         # Update LangGraph state
        #         config = {"configurable": {"thread_id": phone}}
        #         graph.update_state(config, {"operator_active": True})
                
        #     return jsonify({"status": "takeover_complete"})
            
        # except Exception as e:
        #     _logger.error(f"Takeover failed: {e}")
        #     return jsonify({"status": "error"}), 500
        
    elif request.method == "GET":
        return "THIS ENDPOINT IS UP AND WORKS"