from psycopg_pool import ConnectionPool
import psycopg2
import sqlalchemy as db
from sqlalchemy import create_engine, Table, MetaData, insert, update, delete
from sqlalchemy.orm import Session
from config import DB_URL

pool = ConnectionPool(f"postgres://{DB_URL}", min_size = 1, max_size = 5, timeout = 10, kwargs={"autocommit": True})

engine = create_engine(f"postgresql+psycopg2://{DB_URL}")
metadata = MetaData()
metadata.reflect(bind=engine)

user = metadata.tables["user"]
user_conversation = metadata.tables["user_conversation"]
message = metadata.tables["message"]
conversation = metadata.tables["conversation"]


