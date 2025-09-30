from flask import Flask
import os

APP_SECRET_KEY = os.getenv("APP_SECRET_KEY")

if not APP_SECRET_KEY:
    raise EnvironmentError("Missing Secrect Key")

app = Flask(__name__)
app.secret_key = APP_SECRET_KEY



from blueprints.webhook import webhook_bp
from blueprints.operatormsg import operator_bp
from blueprints.handback import handback_bp
from blueprints.takeover import takeover_bp

app.register_blueprint(webhook_bp)
app.register_blueprint(operator_bp)
app.register_blueprint(handback_bp)
app.register_blueprint(takeover_bp)

@app.route("/", methods=["GET"])
def index():
    return "AI BACKEND IS RUNNING", 200