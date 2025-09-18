from psycopg import Connection
from config import DB_URL

with Connection.connect(DB_URL) as conn:
    with conn.cursor() as curr:
        
        curr.execute(query)








