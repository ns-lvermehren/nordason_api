import os
from contextlib import contextmanager
from psycopg_pool import ConnectionPool
from dotenv import load_dotenv

load_dotenv()

# IPv6 Problem umgehen: ?host= Parameter erzwingt IPv4
conninfo = os.getenv("DATABASE_URL") + "?sslmode=require"

pool = ConnectionPool(
    conninfo=conninfo,
    min_size=1,
    max_size=10,
    kwargs={"connect_timeout": 10}
)

@contextmanager
def get_conn(current_user: str = "system"):
    with pool.connection() as conn:
        conn.execute(
            "SELECT set_config('app.current_user', %s, true)",
            (current_user,)
        )
        yield conn