"""Small helpers shared by the app entrypoint and its pages."""
import streamlit as st

from db_connector import get_engine


@st.cache_resource
def shared_engine():
    """One SQLAlchemy engine (and connection pool) for the whole app."""
    return get_engine()


@st.cache_data(ttl="5m")
def check_database():
    """(ok, message) - can we reach the Register database?"""
    try:
        with shared_engine().connect() as conn:
            n = conn.exec_driver_sql("SELECT COUNT(*) FROM sys.tables").scalar()
        return True, f"Connected to Register ({n} tables)"
    except Exception as e:  # noqa: BLE001
        return False, f"Database connection failed: {str(e)[:200]}"
