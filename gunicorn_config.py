import multiprocessing

bind = "0.0.0.0:5000"
backlog = 2048

workers = 5
worker_class = "sync"
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50

# CRITICAL FIX: Increased timeout for media operations
timeout = 180  # 3 minutes (was 30s)
keepalive = 5
graceful_timeout = 30

limit_request_line = 4096
limit_request_fields = 100
limit_request_field_size = 8190

accesslog = "-"
errorlog = "-"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

proc_name = "whatsapp_backend"
daemon = False
pidfile = None

keyfile="/home/ubuntu/ai-backend/certs/privkey.pem"
certfile="/home/ubuntu/ai-backend/certs/fullchain.pem"

preload_app = True

def on_starting(server):
    print("Gunicorn master starting")

def when_ready(server):
    print(f"Gunicorn ready with {server.cfg.workers} workers")

def post_fork(server, worker):
    print(f"Worker {worker.pid} spawned (DB will initialize on first use)")

def post_worker_init(worker):
    print(f"Worker {worker.pid} ready")

def worker_exit(server, worker):
    print(f"Worker {worker.pid} exited")