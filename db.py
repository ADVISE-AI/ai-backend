import sqlalchemy
from sqlalchemy import create_engine, Table, MetaData, insert, update, delete
from sqlalchemy.pool import QueuePool
from config import DB_URL, logger

_logger =  logger(__name__)
try:
    engine = create_engine(
        f"postgresql+psycopg2://{DB_URL}", 
        poolclass=QueuePool,
        pool_size=5,          # Min connections
        max_overflow=10,      # Max additional connections
        pool_timeout=30,      # Wait 30s for connection
        pool_recycle=3600,    # Recycle connections after 1 hour
        pool_pre_ping=True,   # Test connections before use (CRITICAL for SSL)
        connect_args={
            "sslmode": "require",
            "connect_timeout": 10,
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 5,
        }
    )
    # Test connection
    with engine.connect() as conn:
        conn.execute(sqlalchemy.text("SELECT 1"))
    _logger.info("Database connection successful")
except Exception as e:
    _logger.critical(f"Database connection failed: {e}")
    raise

metadata = MetaData()
metadata.reflect(bind=engine)

user = metadata.tables["user"]
user_conversation = metadata.tables["user_conversation"]
message = metadata.tables["message"]
conversation = metadata.tables["conversation"]
sample_library = metadata.tables["sample_media_library"]


