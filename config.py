import os
import logging
from dotenv import load_dotenv

load_dotenv()

required_vars = [
    "APP_SECRET_KEY", "GOOGLE_API_KEY", "WHATSAPP_ACCESS_TOKEN",
    "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_GRAPH_URL",
    "BACKEND_BASE_URL", "AI_BACKEND_URL", "VERIFY_TOKEN", "DB_URL"
]

missing = [var for var in required_vars if not os.getenv(var)]
if missing:
    raise EnvironmentError(f"Missing required env vars: {', '.join(missing)}")

GOOGLE_API_KEY=os.getenv("GOOGLE_API_KEY")
WHATSAPP_ACCESS_TOKEN=os.getenv("WHATSAPP_ACCESS_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_GRAPH_URL = os.getenv("WHATSAPP_GRAPH_URL")
BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL")
AI_BACKEND_URL = os.getenv("AI_BACKEND_URL")
VERIFY_TOKEN=os.getenv("VERIFY_TOKEN")
DB_URL = os.getenv("DB_URL")


def logger(name):
    logging.basicConfig(format='%(asctime)s,%(msecs)03d %(levelname)-8s [%(filename)s:%(lineno)d] %(message)s', datefmt='%Y-%m-%dT%H:%M:%S', level=logging.DEBUG)
    Logger = logging.getLogger(name)
    return Logger
