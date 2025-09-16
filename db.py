import sqlalchemy 
from sqlalchemy import create_engine, Table, MetaData, insert, update, delete
from config import DB_URL


engine = create_engine(f"postgresql+psycopg2://{DB_URL}", pool_pre_ping=True, pool_recycle=300, pool_size=10, max_overflow=20)
metadata = MetaData()
metadata.reflect(bind=engine)

user = metadata.tables["user"]
user_conversation = metadata.tables["user_conversation"]
message = metadata.tables["message"]
conversation = metadata.tables["conversation"]
sample_library = metadata.tables["sample_media_library"]


