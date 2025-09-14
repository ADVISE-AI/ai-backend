from psycopg import Connection
import sqlalchemy 
from sqlalchemy import create_engine, Table, MetaData, insert, update, delete
from sqlalchemy.orm import Session
from config import DB_URL

conn = Connection.connect(f"postgres://{DB_URL}", autocommit=True)

engine = create_engine(f"postgresql+psycopg2://{DB_URL}",  poolclass=sqlalchemy.pool.NullPool, isolation_level="AUTOCOMMIT")
metadata = MetaData()
metadata.reflect(bind=engine)

user = metadata.tables["user"]
user_conversation = metadata.tables["user_conversation"]
message = metadata.tables["message"]
conversation = metadata.tables["conversation"]


