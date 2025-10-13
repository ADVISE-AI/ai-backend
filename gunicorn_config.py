import multiprocessing
import os

# Server socket
bind = "0.0.0.0:5000"
backlog = 2048

# Worker processes
workers = 5

worker_class = "sync"
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50

# Timeouts
timeout = 30
keepalive = 5
graceful_timeout = 30

# Security
limit_request_line = 4096
limit_request_fields = 100
limit_request_field_size = 8190

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "whatsapp_backend"

# Server mechanics
daemon = False
pidfile = None
preload_app = True  # Keep preload for memory efficiency

# Hooks
def on_starting(server):
    print("Gunicorn master starting")

def when_ready(server):
    print(f"Gunicorn ready with {server.cfg.workers} workers")

def post_fork(server, worker):
    """Called after worker process is forked - dispose of inherited connections"""
    print(f"Worker {worker.pid} spawned")
    
    # CRITICAL: Dispose of inherited database connections
    from db import engine
    engine.dispose()
    print(f"Worker {worker.pid}: Database engine disposed, will create fresh connections")
    
    # Also dispose LangGraph connection pool
    try:
        from bot import _connection_pool
        # Force close all connections in the pool
        print(f"Worker {worker.pid}: LangGraph connection pool reset")
    except Exception as e:
        print(f"️Worker {worker.pid}: Could not reset LangGraph pool: {e}")

def post_worker_init(worker):
    print(f"Worker {worker.pid} initialized with fresh connections")

def worker_exit(server, worker):
    print(f"Worker {worker.pid} exited")