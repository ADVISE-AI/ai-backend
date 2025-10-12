import sqlalchemy
from sqlalchemy import create_engine, Table, MetaData, event
from sqlalchemy.pool import QueuePool, Pool
from sqlalchemy.exc import DisconnectionError, OperationalError, DBAPIError
from config import DB_URL, logger
import time

_logger = logger(__name__)

# Connection statistics
connection_stats = {
    "created": 0,
    "closed": 0,
    "errors": 0,
    "pre_ping_failures": 0,
    "reconnections": 0
}

# AWS RDS-specific disconnect detection
def is_disconnect_error(e, connection, cursor):
    """
    Detect if an error is a disconnect error (AWS RDS optimized)
    Returns True if connection should be invalidated
    """
    if isinstance(e, (DisconnectionError, OperationalError)):
        return True
    
    error_msg = str(e).lower()
    
    # AWS RDS-specific error patterns
    rds_errors = [
        'ssl',
        'connection',
        'closed',
        'broken',
        'reset',
        'timeout',
        'bad record mac',
        'decryption failed',
        'connection refused',
        'no route to host',
        'terminating connection',  # RDS-specific
        'the connection has been closed',  # RDS-specific
        'network error',
        'broken pipe'
    ]
    
    for error_pattern in rds_errors:
        if error_pattern in error_msg:
            _logger.warning(f"Detected disconnect: '{error_pattern}' in error")
            connection_stats["errors"] += 1
            return True
    
    return False

@event.listens_for(Pool, "connect")
def receive_connect(dbapi_conn, connection_record):
    """Called when new connection is created"""
    connection_stats["created"] += 1
    _logger.info(f"✓ New DB connection #{connection_stats['created']}")
    
    # Set AWS RDS-optimized connection parameters
    try:
        cursor = dbapi_conn.cursor()
        # Prevent long-running queries
        cursor.execute("SET statement_timeout = '30s'")
        # Kill idle transactions
        cursor.execute("SET idle_in_transaction_session_timeout = '60s'")
        cursor.close()
    except Exception as e:
        _logger.warning(f"Could not set connection parameters: {e}")

@event.listens_for(Pool, "checkout")
def receive_checkout(dbapi_conn, connection_record, connection_proxy):
    """Log when connection is taken from pool"""
    _logger.debug(f"↗Connection checked out")

@event.listens_for(Pool, "checkin")
def receive_checkin(dbapi_conn, connection_record):
    """Log when connection is returned to pool"""
    _logger.debug(f"↙Connection returned to pool")

@event.listens_for(Pool, "close")
def receive_close(dbapi_conn, connection_record):
    """Called when connection is closed"""
    connection_stats["closed"] += 1
    _logger.info(f"Connection closed (total: {connection_stats['closed']})")

@event.listens_for(Pool, "invalidate")
def receive_invalidate(dbapi_conn, connection_record, exception):
    """Called when connection is invalidated (dead connection detected)"""
    connection_stats["pre_ping_failures"] += 1
    connection_stats["reconnections"] += 1
    if exception:
        _logger.warning(f"Connection invalidated (#{connection_stats['pre_ping_failures']}): {exception}")
    else:
        _logger.warning(f"Connection invalidated (#{connection_stats['pre_ping_failures']})")

# Create engine with AWS RDS-specific optimizations
try:
    engine = create_engine(
        f"postgresql+psycopg2://{DB_URL}",
        
        # Pool configuration optimized for AWS RDS
        poolclass=QueuePool,
        pool_size=3,              # Small pool for Flask app
        max_overflow=7,           # Up to 10 total connections
        pool_timeout=30,          # Wait 30s for connection
        
        # CRITICAL FOR AWS RDS: Recycle before NAT timeout (350s)
        # Set to 5 minutes (300s) to be safe
        pool_recycle=300,         # Recycle every 5 minutes!
        
        pool_pre_ping=True,       # Test before use
        pool_use_lifo=True,       # Use most recent connection (keeps pool fresh)
        
        # AWS RDS-optimized connection settings
        connect_args={
            "sslmode": "require",
            "connect_timeout": 10,
            
            # CRITICAL: TCP keepalive MUST be less than NAT timeout (350s)
            # We'll use 60s to be very aggressive
            "keepalives": 1,
            "keepalives_idle": 60,      # Start sending keepalives after 60s idle
            "keepalives_interval": 10,   # Send every 10s
            "keepalives_count": 5,       # Try 5 times before giving up
            
            # Application identification
            "application_name": "flask_ai_backend",
            
            # Prevent hanging queries
            "options": "-c statement_timeout=30000 -c idle_in_transaction_session_timeout=60000"
        },
        
        # Always rollback on connection return
        pool_reset_on_return='rollback',
        
        # Use READ COMMITTED to avoid lock issues
        isolation_level="READ COMMITTED",
        
        # Execution options
        execution_options={
            "isolation_level": "READ COMMITTED"
        }
    )
    
    # Register disconnect handler
    event.listen(engine, "handle_error", is_disconnect_error)
    
    # Test connection with retries
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with engine.connect() as conn:
                result = conn.execute(sqlalchemy.text("SELECT version(), current_database()"))
                version, db_name = result.fetchone()
                _logger.info(f"✓ Connected to AWS RDS")
                _logger.info(f"  Database: {db_name}")
                _logger.info(f"  PostgreSQL: {version.split()[0]} {version.split()[1]}")
            break
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                _logger.warning(f"Connection attempt {attempt + 1} failed: {e}")
                _logger.info(f"Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                _logger.critical(f"Database connection failed after {max_retries} attempts: {e}")
                raise
    
except Exception as e:
    _logger.critical(f"Failed to initialize database engine: {e}")
    raise

# Load table metadata
metadata = MetaData()
try:
    metadata.reflect(bind=engine)
    _logger.info(f"✓ Loaded {len(metadata.tables)} tables: {', '.join(list(metadata.tables.keys())[:5])}...")
except Exception as e:
    _logger.error(f"Failed to load table metadata: {e}")
    raise

# Table references
user = metadata.tables.get("user")
user_conversation = metadata.tables.get("user_conversation")
message = metadata.tables.get("message")
conversation = metadata.tables.get("conversation")
sample_library = metadata.tables.get("sample_media_library")

# Verify critical tables
critical_tables = ["user", "conversation", "message"]
missing_tables = [t for t in critical_tables if t not in metadata.tables]
if missing_tables:
    _logger.critical(f"Missing critical tables: {missing_tables}")
    raise RuntimeError(f"Database schema incomplete: missing {missing_tables}")

_logger.info(f"✓ All critical tables present")


def get_connection_stats():
    """Get current connection pool statistics"""
    pool = engine.pool
    return {
        "connections": {
            "created": connection_stats["created"],
            "closed": connection_stats["closed"],
            "errors": connection_stats["errors"],
            "pre_ping_failures": connection_stats["pre_ping_failures"],
            "reconnections": connection_stats["reconnections"],
            "success_rate": f"{((connection_stats['created'] - connection_stats['errors']) / max(connection_stats['created'], 1) * 100):.1f}%"
        },
        "pool": {
            "size": pool.size(),
            "checked_in": pool.checkedin(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "total_capacity": pool.size() + engine.pool._max_overflow,
            "utilization": f"{(pool.checkedout() / (pool.size() + engine.pool._max_overflow) * 100):.1f}%"
        }
    }


def execute_with_retry(func, max_retries=3, initial_backoff=0.1):
    """
    Execute database operation with automatic retry on connection errors
    
    Designed for AWS RDS intermittent connection issues
    """
    for attempt in range(max_retries):
        try:
            return func()
        except (OperationalError, DBAPIError) as e:
            error_msg = str(e).lower()
            is_connection_error = any(
                keyword in error_msg 
                for keyword in ['ssl', 'connection', 'closed', 'broken', 'timeout', 'network']
            )
            
            if is_connection_error and attempt < max_retries - 1:
                backoff = initial_backoff * (2 ** attempt)
                _logger.warning(f"DB operation failed (attempt {attempt + 1}/{max_retries}): {str(e)[:100]}")
                _logger.info(f"Retrying in {backoff:.2f}s...")
                time.sleep(backoff)
                continue
            raise


def healthcheck():
    """Quick database health check"""
    try:
        with engine.connect() as conn:
            conn.execute(sqlalchemy.text("SELECT 1"))
        return {"status": "healthy", "message": "Database responsive"}
    except Exception as e:
        _logger.error(f"Health check failed: {e}")
        return {"status": "unhealthy", "error": str(e)}


# Log initialization summary
_logger.info("=" * 60)
_logger.info("DATABASE ENGINE INITIALIZED")
_logger.info(f"  Pool Size: {engine.pool.size()} + {engine.pool._max_overflow} overflow")
_logger.info(f"  Recycle: {engine.pool._recycle}s (every 5 min)")
_logger.info(f"  TCP Keepalive: 60s idle, 10s interval")
_logger.info("=" * 60)