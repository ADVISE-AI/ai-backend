import os
import logging
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY=os.getenv("OPENAI_API_KEY")
GOOGLE_API_KEY=os.getenv("GEMINI_API_KEY")
WHATSAPP_ACCESS_TOKEN=os.getenv("WHATSAPP_ACCESS_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
VERIFY_TOKEN=os.getenv("VERIFY_TOKEN")
DB_URL = os.getenv("DB_URL")

def logger(name):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    Logger = logging.getLogger(name)
    return Logger
