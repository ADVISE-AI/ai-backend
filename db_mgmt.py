from psycopg import Connection
from config import DB_URL

with Connection.connect(DB_URL) as conn:
    with conn.cursor() as curr:
        #query = """ DROP TABLE checkpoints; DROP TABLE checkpoint_migrations; DROP TABLE checkpoint_writes; DROP TABLE checkpoint_blobs;"""

        curr.execute(query)








