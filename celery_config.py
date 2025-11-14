# Celery Configuration
broker_url = 'redis://localhost:6379/0'
result_backend = 'redis://localhost:6379/0'

# Serialization
task_serializer = 'json'
accept_content = ['json']
result_serializer = 'json'
result_expires = 3600

# Timezone
timezone = 'Asia/Kolkata'
enable_utc = True

# Task execution
task_track_started = True
task_time_limit = 300  # 5 minutes hard limit
task_soft_time_limit = 240  # 4 minutes soft limit
task_acks_late = True
worker_prefetch_multiplier = 1

# Reliability
task_reject_on_worker_lost = True
task_acks_on_failure_or_timeout = True

# Performance
worker_max_tasks_per_child = 100
worker_disable_rate_limits = True

# Monitoring
worker_send_task_events = True
task_send_sent_event = True

# Connection pool
broker_pool_limit = 10
broker_connection_retry_on_startup = True
broker_connection_max_retries = 10

# Task routes (already defined in tasks.py, but can override here)
task_routes = {
    'tasks.process_message': {'queue': 'messages'},
    'tasks.check_buffer': {'queue': 'messages'},
    'tasks.update_message_status': {'queue': 'status'},
}

# Result backend settings
result_backend_transport_options = {
    'master_name': 'mymaster'
}