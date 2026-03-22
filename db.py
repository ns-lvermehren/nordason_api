import os
from contextlib import contextmanager
from psycopg2.pool import ThreadedConnectionPool
from dotenv import load_dotenv

load_dotenv()

pool = ThreadedConnectionPool(
    minconn=2,
    maxconn=10,
    dsn=os.getenv("DATABASE_URL"),
    sslmode="require"
)

@contextmanager
def get_conn(current_user: str = "system"):
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT set_config('app.current_user', %s, true)",
                (current_user,)
            )
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)