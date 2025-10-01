from flask import Blueprint, request, jsonify
from config import logger, BACKEND_BASE_URL
from utility.whatsapp import get_url

fetch_media_bp = Blueprint('fetch_media', __name__)
_logger = logger(__name__)

@fetch_media_bp.route("/media", methods=["GET"])
def fetch_media():
    media_id = request.args.get("id")

    if not media_id:
        return jsonify({"status": "error", "message": "Missing media id"}), 400

    return jsonify(get_url(media_id))

