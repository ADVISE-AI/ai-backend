#!/usr/bin/env python3
"""
Server startup script for WhatsApp AI Backend
Compatible with both local & production environments
"""

import uvicorn
import multiprocessing
import os
from dotenv import load_dotenv
from config import (
    DB_URL, GOOGLE_API_KEY, WHATSAPP_ACCESS_TOKEN, WHATSAPP_PHONE_NUMBER_ID,
    WHATSAPP_GRAPH_URL, BACKEND_BASE_URL, AI_BACKEND_URL, VERIFY_TOKEN, REDIS_URI,
    logger
)

# Load local .env only if running in development
if not os.getenv("ENVIRONMENT"):
    load_dotenv()

def main():
    workers = int(os.getenv("WORKERS", multiprocessing.cpu_count()))
    environment = os.getenv("ENVIRONMENT", "development")

    # Base path (project root)
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

    # SSL file paths
    ssl_keyfile = os.getenv("SSL_KEYFILE")
    ssl_certfile = os.getenv("SSL_CERTFILE")

    # Convert relative paths to absolute (for local envs)
    if ssl_keyfile and not os.path.isabs(ssl_keyfile):
        ssl_keyfile = os.path.join(BASE_DIR, ssl_keyfile)
    if ssl_certfile and not os.path.isabs(ssl_certfile):
        ssl_certfile = os.path.join(BASE_DIR, ssl_certfile)

    # Check if SSL files exist
    use_ssl = ssl_keyfile and ssl_certfile and os.path.exists(ssl_keyfile) and os.path.exists(ssl_certfile)

    # Uvicorn configuration
    config = {
        "app": "app:app",
        "host": "127.0.0.1",
        "port": 5000,
        "workers": workers,
        "log_level": os.getenv("LOG_LEVEL", "info"),
        "access_log": True,
        "proxy_headers": True,
        "forwarded_allow_ips": "*",
    }

    # Use SSL if available (only in production)
    if use_ssl and environment == "production":
        config["ssl_keyfile"] = ssl_keyfile
        config["ssl_certfile"] = ssl_certfile
        print("🔒 SSL Enabled (Production mode)")
    else:
        print("⚙️  Running without SSL (Development mode)")

    # Enable autoreload in local development
    if environment == "development":
        config["reload"] = True
        config["reload_dirs"] = [".", "blueprints", "utility", "agent_tools"]
        config["workers"] = 1
        print("🔄 Auto-reload enabled (Development mode)")

    print("=" * 60)
    print(f"🚀 Environment: {environment}")
    print(f"Workers:      {config['workers']}")
    print(f"SSL:          {'✅ Enabled' if use_ssl else '❌ Disabled'}")
    print("=" * 60)
    uvicorn.run(**config)

if __name__ == "__main__":
    main()
