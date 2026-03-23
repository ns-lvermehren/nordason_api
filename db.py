# db.py
import os
from contextlib import contextmanager
from psycopg_pool import ConnectionPool
from dotenv import load_dotenv

load_dotenv()

pool = ConnectionPool(
    conninfo=os.getenv("DATABASE_URL"),
    min_size=0,
    max_size=10,
    open=False,
    kwargs={"connect_timeout": 30, "autocommit": False},
    timeout=60
)

@contextmanager
def get_conn(current_user: str = "system"):
    with pool.connection() as conn:
        conn.execute(
            "SELECT set_config('app.current_user', %s, true)",
            (current_user,)
        )
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise