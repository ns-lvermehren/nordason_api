import os
from contextlib import contextmanager
from psycopg_pool import ConnectionPool
from dotenv import load_dotenv

load_dotenv()

pool = ConnectionPool(
    conninfo=os.getenv("DATABASE_URL"),
    min_size=0,           # kein sofortiger Verbindungsaufbau beim Start
    max_size=10,
    open=False,           # Pool erst beim ersten Request öffnen
    kwargs={"connect_timeout": 10}
)

@contextmanager
def get_conn(current_user: str = "system"):
    if not pool.closed:
        pass
    else:
        pool.open()

    with pool.connection() as conn:
        conn.execute(
            "SELECT set_config('app.current_user', %s, true)",
            (current_user,)
        )
        yield conn