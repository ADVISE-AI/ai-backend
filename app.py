from flask import Flask, request, jsonify
from config import logger
from db import engine
import os

APP_SECRET_KEY = os.getenv("APP_SECRET_KEY")

if not APP_SECRET_KEY:
    raise EnvironmentError("Missing Secrect Key")

app = Flask(__name__)
app.secret_key = APP_SECRET_KEY

_logger = logger(__name__)

@app.before_request
def log_request():
    logger("app").info(f"{request.method} {request.path} from {request.remote_addr}")

@app.after_request
def log_response(response):
    logger("app").info(f"Response: {response.status_code}")
    return response

from blueprints.webhook import webhook_bp
from blueprints.operatormsg import operator_bp
from blueprints.handback import handback_bp
from blueprints.takeover import takeover_bp
from blueprints.fetch_media import fetch_media_bp

app.register_blueprint(webhook_bp)
app.register_blueprint(operator_bp)
app.register_blueprint(handback_bp)
app.register_blueprint(takeover_bp)
app.register_blueprint(fetch_media_bp)

@app.route("/", methods=["GET"])
def index():
    return "AI BACKEND IS RUNNING", 200

@app.route("/health", methods=["GET"])
def health_check():
    try:
        with engine.connect() as conn:
            conn.execute("SELECT 1")
            return jsonify({"status": "healthy", "database": "connected"}), 200
    except Exception as e:
        _logger("app").error(f"Health check failed: {e}")
        return jsonify({"status": "error", "message": "Internal Server Error"}), 500
    return jsonify({"status": "success", "message": "OK"}), 200

@app.errorhandler(500)
def handle_500(e):
    _logger("app").error(f"Internal error: {e}")
    return "Internal Server Error", 500

@app.errorhandler(404)
def handle_404(e):
    return "Not Found", 404

@app.errorhandler(Exception)
def handle_exception(e):
    _logger.error(f"Unhandled exception: {e}")
    return "Something went wrong", 500