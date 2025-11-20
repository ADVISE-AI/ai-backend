import sqlalchemy
from sqlalchemy import create_engine, Table, MetaData
from sqlalchemy.pool import QueuePool
from config import DB_URL, logger
import threading
import os

_logger = logger(__name__)
_init_lock = threading.Lock()
# Will be initialized lazily per-process
_engine = None
_metadata = None
_tables = {}
_process_id = None


def _initialize_db():
    """Initialize database engine and metadata for current process"""
    global _engine, _metadata, _tables, _process_id
    
    current_pid = os.getpid()
    
    # If engine exists but we're in a different process (after fork)
    if _engine is not None and _process_id != current_pid:
        _logger.info(f"Fork detected (PID {_process_id} → {current_pid}), creating new engine")
        try:
            _engine.dispose()
        except Exception as e:
            _logger.warning(f"Failed to dispose old engine: {e}")
        finally:
            _engine = None
            _metadata = None
            _tables = {} 

    if _engine is None:
        _logger.info(f"Initializing database for PID {current_pid}")
        
        _engine = create_engine(
            f"postgresql+psycopg2://{DB_URL}",
            poolclass=QueuePool,
            pool_pre_ping=True,
            pool_size=5,              # 5 connections per worker
            max_overflow=10,          # +10 temporary connections
            pool_recycle=300,
            pool_timeout=30,
            connect_args={
                # "sslmode": "require",
                "connect_timeout": 10,
                "keepalives": 1,
                "keepalives_idle": 30,
                "keepalives_interval": 10,
                "keepalives_count": 5,
            }
        )
        
        # Reflect metadata
        _metadata = MetaData()
        _metadata.reflect(bind=_engine)
        
        # Cache table references
        _tables['user'] = _metadata.tables["user"]
        _tables['user_conversation'] = _metadata.tables["user_conversation"]
        _tables['message'] = _metadata.tables["message"]
        _tables['conversation'] = _metadata.tables["conversation"]
        # Legacy sample library table (if present)
        if "sample_media_library" in _metadata.tables:
            _tables['sample_library'] = _metadata.tables["sample_media_library"]
        # New media/catalog tables (if present)
        if "media_files" in _metadata.tables:
            _tables['media_files'] = _metadata.tables["media_files"]
        if "categories" in _metadata.tables:
            _tables['categories'] = _metadata.tables["categories"]
        
        _process_id = current_pid
        
        # Test connection
        with _engine.connect() as conn:
            conn.execute(sqlalchemy.text("SELECT 1"))
        
        _logger.info(f"✅ Database initialized for PID {current_pid} (pool_size=5, max_overflow=10)")


def get_engine():
    """Get database engine (lazy initialization)"""
    if _engine is None or _process_id != os.getpid():
        _initialize_db()
    return _engine


def __getattr__(name):
    if name in (
        'engine',
        'user',
        'user_conversation',
        'message',
        'conversation',
        'sample_library',
        'media_files',
        'categories',
    ):
        if _engine is None or _process_id != os.getpid():
            with _init_lock:
                # Double-check pattern
                if _engine is None or _process_id != os.getpid():
                    _initialize_db()
        
        if name == 'engine':
            return _engine
        else:
            return _tables.get(name)
    
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")