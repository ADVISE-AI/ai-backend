# FastAPI imports
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import time
import redis.asyncio as redis
import uvicorn
import os

# Local imports
from db import get_engine
from config import (
    logger, 
    DB_URL, 
    GOOGLE_API_KEY, 
    WHATSAPP_ACCESS_TOKEN, 
    WHATSAPP_PHONE_NUMBER_ID,
    WHATSAPP_GRAPH_URL, 
    BACKEND_BASE_URL, 
    AI_BACKEND_URL, 
    VERIFY_TOKEN, 
    REDIS_URI
)

_logger = logger(__name__)

# Lifespan context manager for startup/shutdown events
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager
    Handles startup and shutdown events
    """
    # Startup
    _logger.info("🚀 Starting WhatsApp AI Backend...")
    
    try:
        # Test database connection
        engine = get_engine()
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        _logger.info("✅ Database connection verified")
    except Exception as e:
        _logger.error(f"❌ Database connection failed: {e}")
        raise
    
    try:
        # Test Redis connection
        redis_client = redis.from_url(REDIS_URI, decode_responses=True)
        await redis_client.ping()
        await redis_client.close()
        _logger.info("✅ Redis connection verified")
    except Exception as e:
        _logger.error(f"❌ Redis connection failed: {e}")
        raise
    
    _logger.info("✅ All systems operational")
    
    yield  # Application runs here
    
    # Shutdown
    _logger.info("🛑 Shutting down WhatsApp AI Backend...")
    
    try:
        engine = get_engine()
        engine.dispose()
        _logger.info("✅ Database connections closed")
    except Exception as e:
        _logger.warning(f"⚠️ Error closing database: {e}")
    
    _logger.info("👋 Shutdown complete")


# Initialize FastAPI app
app = FastAPI(
    title="WhatsApp AI Backend",
    description="AI-powered WhatsApp Business API integration",
    version="1.0.0",
    docs_url="/docs" if os.getenv("ENVIRONMENT") == "development" else None,
    redoc_url=None,
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request timing middleware
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    """Add processing time to response headers"""
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(round(process_time * 1000, 2))
    return response

# Logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all requests and responses"""
    # Skip health check logging to reduce noise
    if request.url.path != "/health":
        _logger.info(
            f"→ {request.method} {request.url.path} "
            f"from {request.client.host if request.client else 'unknown'}"
        )
    
    response = await call_next(request)
    
    if request.url.path != "/health":
        _logger.info(f"← {response.status_code} for {request.url.path}")
    
    return response

# Register routers (blueprints)
from blueprints.webhook import router as webhook_router
from blueprints.operatormsg import router as operator_router, legacy_router as legacy_operator_router
from blueprints.handback import router as handback_router, legacy_router as legacy_handback_router
from blueprints.takeover import router as takeover_router, legacy_router as legacy_takeover_router
from blueprints.fetch_media import router as fetch_media_router

app.include_router(webhook_router, tags=["Webhook"])
app.include_router(operator_router, tags=["Operator"])
app.include_router(handback_router, tags=["Operator"])
app.include_router(takeover_router, tags=["Operator"])
app.include_router(fetch_media_router, tags=["Media"])

# Legacy compatibility routes (without /api/v1/ prefix)
app.include_router(legacy_operator_router, tags=["Legacy Operator"])
app.include_router(legacy_handback_router, tags=["Legacy Operator"])
app.include_router(legacy_takeover_router, tags=["Legacy Operator"])

_logger.info("✅ All routers registered")


# Root endpoint
@app.get("/", tags=["Status"])
async def root():
    """
    Root endpoint - service status
    """
    return {
        "service": "WhatsApp AI Backend",
        "status": "running",
        "version": "2.0.0",
        "environment": os.getenv("ENVIRONMENT", "development"),
        "docs": "/docs" if os.getenv("ENVIRONMENT") == "development" else "disabled"
    }


# Health check endpoint
@app.get("/health", tags=["Status"])
async def health_check():
    """
    Comprehensive health check
    Checks: Database, Redis, Celery workers
    """
    health_status = {
        "status": "healthy",
        "checks": {},
        "timestamp": time.time()
    }
    
    all_healthy = True
    
    # Check 1: Database
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        health_status["checks"]["database"] = "connected"
    except Exception as e:
        _logger.error(f"Database health check failed: {e}")
        health_status["checks"]["database"] = f"error: {str(e)[:100]}"
        all_healthy = False
    
    # Check 2: Redis
    try:
        redis_client = redis.from_url(REDIS_URI, decode_responses=True)
        await redis_client.ping()
        await redis_client.close()
        health_status["checks"]["redis"] = "connected"
    except Exception as e:
        _logger.error(f"Redis health check failed: {e}")
        health_status["checks"]["redis"] = f"error: {str(e)[:100]}"
        all_healthy = False
    
    # Check 3: Celery workers (optional)
    try:
        from celery import Celery
        celery_app = Celery("webhook", broker=REDIS_URI)
        inspect = celery_app.control.inspect()
        active_workers = inspect.active()
        
        if active_workers:
            worker_count = len(active_workers)
            health_status["checks"]["celery"] = f"{worker_count} workers active"
        else:
            health_status["checks"]["celery"] = "no workers detected"
            _logger.warning("No Celery workers detected")
    except Exception as e:
        _logger.warning(f"Celery health check failed: {e}")
        health_status["checks"]["celery"] = "unavailable"
    
    # Set overall status
    if all_healthy:
        health_status["status"] = "healthy"
        return JSONResponse(content=health_status, status_code=200)
    else:
        health_status["status"] = "degraded"
        return JSONResponse(content=health_status, status_code=503)


# Stats endpoint
@app.get("/stats", tags=["Status"])
async def stats():
    """
    Service statistics
    Returns: Buffer stats, deduplication stats, system info
    """
    try:
        from utility.message_buffer import get_message_buffer
        from utility.message_deduplicator import get_dedup_stats
        
        buffer = get_message_buffer()
        
        stats_data = {
            "buffer": buffer.get_buffer_stats(),
            "deduplication": get_dedup_stats(),
            "environment": os.getenv("ENVIRONMENT", "development"),
            "timestamp": time.time()
        }
        
        return stats_data
    except Exception as e:
        _logger.error(f"Failed to get stats: {e}")
        return JSONResponse(
            content={"error": "Failed to retrieve stats", "detail": str(e)},
            status_code=500
        )


# Error handlers
@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    """Handle 404 Not Found errors"""
    return JSONResponse(
        status_code=404,
        content={
            "error": "Not Found",
            "message": f"The requested URL {request.url.path} was not found",
            "path": request.url.path
        }
    )


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc):
    """Handle 500 Internal Server errors"""
    _logger.error(f"Internal server error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal Server Error",
            "message": "An unexpected error occurred"
        }
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """Handle all unhandled exceptions"""
    _logger.error(f"Unhandled exception: {exc}", exc_info=True)
    
    # Show details in debug mode
    if os.getenv("ENVIRONMENT") == "development":
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal Error",
                "message": str(exc),
                "type": type(exc).__name__,
                "path": request.url.path
            }
        )
    else:
        return JSONResponse(
            status_code=500,
            content={
                "error": "Something went wrong",
                "message": "Please try again later"
            }
        )


# Run with uvicorn if executed directly
if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=5000,
        reload=True,
        log_level="info",
        access_log=True,
        ssl_keyfile=None,
        ssl_certfile=None,
    )