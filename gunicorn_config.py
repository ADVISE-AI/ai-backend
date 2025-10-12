import multiprocessing
import os

# Server socket
bind = "0.0.0.0:5000"
backlog = 2048

# Worker processes
workers = multiprocessing.cpu_count() * 2 + 1  # Common formula
# OR manually set based on your server:
# workers = 4  # For 2 CPU cores
# workers = 6  # For 3 CPU cores  
# workers = 8  # For 4 CPU cores

worker_class = "sync"  # Default, good for Flask
worker_connections = 1000
max_requests = 1000  # Restart workers after 1000 requests (prevents memory leaks)
max_requests_jitter = 50  # Add randomness to prevent all workers restarting at once

# Timeouts
timeout = 30  # Workers are killed after 30s (webhooks should be fast!)
keepalive = 5  # Keep connections alive for 5s
graceful_timeout = 30  # Give workers 30s to finish during shutdown

# Security
limit_request_line = 4096
limit_request_fields = 100
limit_request_field_size = 8190

# Logging
accesslog = "-"  # Log to stdout
errorlog = "-"   # Log to stderr
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "whatsapp_backend"

# Server mechanics
daemon = False  # Don't daemonize (use systemd instead)
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None

# SSL (if not using nginx)
keyfile = "/home/ubuntu/ai-backend/certs/privkey.pem"
certfile = "/home/ubuntu/ai-backend/certs/fullchain.pem"

# Preload app (load before forking workers)
preload_app = True  # Saves memory, but harder to reload

# Hook for worker initialization
def on_starting(server):
    """Called just before the master process is initialized."""
    print("🚀 Gunicorn master starting")

def when_ready(server):
    """Called just after the server is started."""
    print(f"✅ Gunicorn ready with {workers} workers")

def on_reload(server):
    """Called to recycle workers during a reload via SIGHUP."""
    print("🔄 Gunicorn reloading")

def worker_int(worker):
    """Called when a worker receives the SIGINT or SIGQUIT signal."""
    print(f"⚠️  Worker {worker.pid} interrupted")

def pre_fork(server, worker):
    """Called just before a worker is forked."""
    pass

def post_fork(server, worker):
    """Called just after a worker has been forked."""
    print(f"👷 Worker {worker.pid} spawned")

def post_worker_init(worker):
    """Called just after a worker has initialized the application."""
    print(f"✅ Worker {worker.pid} initialized")

def worker_exit(server, worker):
    """Called just after a worker has been exited."""
    print(f"👋 Worker {worker.pid} exited")