import sqlalchemy
from sqlalchemy import create_engine, Table, MetaData, insert, update, delete
from config import DB_URL, logger

_logger =  logger(__name__)
try:
    engine = create_engine(
        f"postgresql+psycopg2://{DB_URL}", 
        pool_pre_ping=True, 
        pool_recycle=300, 
        pool_size=10, 
        max_overflow=20
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


