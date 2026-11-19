"""Small helpers shared by the app entrypoint and its pages."""
import streamlit as st

from db_connector import ensure_setup, get_engine, sync_catalog


@st.cache_resource
def shared_engine():
    """One SQLAlchemy engine (and connection pool) for the whole app."""
    engine = get_engine()
    try:
        ensure_setup(engine)            # try_float() / try_int() helpers + _catalog table
        sync_catalog(engine)            # make every table in Supabase visible to the app
    except Exception:                   # noqa: BLE001 - the connection check below reports the real problem
        pass
    return engine


@st.cache_data(ttl="30s")
def check_database():
    """(ok, message) - can we reach the Register database?"""
    try:
        with shared_engine().connect() as conn:
            n = conn.exec_driver_sql(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public'").scalar()
        return True, f"Connected to Supabase ({n} tables)"
    except Exception as e:  # noqa: BLE001
        return False, f"Database connection failed: {str(e)[:200]}"
