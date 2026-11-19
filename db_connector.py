"""
Database connector for the BI Assistant Bot project.

Connects to the Supabase (PostgreSQL) database that holds the GDIC Register tables.
The connection string comes from SUPABASE_DB_URL in the .env file (or an environment variable /
Streamlit secret of the same name):

    SUPABASE_DB_URL="postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres"

Use in other files:
    from db_connector import get_engine, test_connection, qi
    engine = get_engine()

Check the connection from the terminal:
    python db_connector.py
"""
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

load_dotenv()

SCHEMA = "public"


def qi(name):
    """Quote an identifier for PostgreSQL (table / column names keep their exact case)."""
    return '"' + str(name).replace('"', '""') + '"'


def _url():
    load_dotenv(override=True)             # pick up .env edits without restarting the app
    url = os.getenv("SUPABASE_DB_URL")
    if not url:
        try:                                      # also allow .streamlit/secrets.toml
            import streamlit as st
            url = st.secrets.get("SUPABASE_DB_URL")
        except Exception:                         # noqa: BLE001
            url = None
    if not url or "[YOUR-PASSWORD]" in url or "xxxxxxxx" in url:
        raise RuntimeError(
            "SUPABASE_DB_URL is not set. Put your Supabase connection string in the .env file "
            "(Supabase > Project Settings > Database > Connection string > URI).")
    u = make_url(url.strip())
    if u.drivername in ("postgres", "postgresql"):
        u = u.set(drivername="postgresql+psycopg")
    if "sslmode" not in u.query:
        u = u.update_query_dict({"sslmode": "require"})
    return u


def get_engine():
    """Return a SQLAlchemy engine for the Supabase database."""
    return create_engine(_url(), pool_size=5, max_overflow=5, pool_pre_ping=True, pool_recycle=300,
                         connect_args={"prepare_threshold": None})   # needed for Supabase's pooler


# Safe casts (SQL Server's TRY_CAST) and the catalog table the app reads. Idempotent.
SETUP_SQL = [
    r"""CREATE OR REPLACE FUNCTION public.try_float(t text) RETURNS double precision
        LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
        SELECT CASE WHEN replace(t, ',', '') ~ '^\s*[-+]?([0-9]+\.?[0-9]*|\.[0-9]+)([eE][-+]?[0-9]+)?\s*$'
                    THEN replace(t, ',', '')::double precision END $$""",
    r"""CREATE OR REPLACE FUNCTION public.try_int(t text) RETURNS integer
        LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
        SELECT CASE WHEN t ~ '^\s*[-+]?[0-9]{1,9}(\.0*)?\s*$' THEN t::numeric::integer END $$""",
    """CREATE TABLE IF NOT EXISTS public._catalog (
        table_name   text PRIMARY KEY,
        source_path  text NOT NULL,
        sheet_name   text,
        file_mtime   timestamp,
        row_count    bigint,
        column_count integer,
        status       text NOT NULL,
        message      text,
        loaded_at    timestamp NOT NULL DEFAULT now()
    )""",
]


def ensure_setup(engine=None):
    """Create the helper functions and the _catalog table if they are missing."""
    engine = engine or get_engine()
    with engine.begin() as conn:
        for stmt in SETUP_SQL:
            conn.exec_driver_sql(stmt.replace("%", "%%"))


def sync_catalog(engine=None):
    """Register every table in schema public that is missing from _catalog (e.g. tables created in the
    Supabase dashboard or uploaded directly), so the app can see it. 'collection_register' is listed
    as the file 'Collection Register.xlsx' under the folder 'Excel'."""
    engine = engine or get_engine()
    with engine.begin() as conn:
        missing = [r[0] for r in conn.exec_driver_sql(
            "SELECT t.table_name FROM information_schema.tables t "
            "WHERE t.table_schema = 'public' AND t.table_type = 'BASE TABLE' AND left(t.table_name, 1) <> '_' "
            "AND NOT EXISTS (SELECT 1 FROM public._catalog c WHERE c.table_name = t.table_name) "
            "ORDER BY t.table_name")]
        for t in missing:
            rows = conn.exec_driver_sql(f"SELECT COUNT(*) FROM {qi(t)}").scalar()
            ncols = conn.exec_driver_sql(
                "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = 'public' "
                "AND table_name = %s", (t,)).scalar()
            file_name = " ".join(w.capitalize() for w in t.split("_")) + ".xlsx"
            conn.exec_driver_sql(
                "INSERT INTO public._catalog (table_name, source_path, sheet_name, file_mtime, row_count,"
                " column_count, status, message) VALUES (%s, %s, NULL, now(), %s, %s, 'ok', 'auto-registered')",
                (t, f"Excel/{file_name}", rows, ncols))


def test_connection():
    """Connect, run a few checks, and print the result. Returns True if it worked."""
    try:
        with get_engine().connect() as conn:
            db = conn.execute(text("SELECT current_database()")).scalar()
            tables = conn.execute(text(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public'")).scalar()
            print(f"Connected to Supabase database '{db}' ({tables} tables in schema public).")
            rows = conn.execute(text('SELECT * FROM public._catalog LIMIT 5')).fetchall()
            print("First rows of public._catalog:")
            for r in rows:
                print("  ", tuple(r))
        return True
    except Exception as e:  # noqa: BLE001
        print(f"Connection FAILED: {e}")
        return False


if __name__ == "__main__":
    test_connection()
