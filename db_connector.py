"""
Database connector for the BI Assistant Bot project.

Connects to the SQL Server database [Register] on localhost\\SQLEXPRESS
using Windows authentication (no password needed).

Use in other files:
    from db_connector import get_engine, test_connection
    engine = get_engine()                    # Register
    engine_v2 = get_engine("Register_V2")    # the copy

Check the connection from the terminal:
    python db_connector.py
"""
from urllib.parse import quote_plus

import pyodbc
from sqlalchemy import create_engine, text

# ---- settings -------------------------------------------------------------
SERVER = r"localhost\SQLEXPRESS"
DEFAULT_DATABASE = "Register"
PREFERRED_DRIVERS = ["ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server"]


def _pick_driver():
    installed = pyodbc.drivers()
    for d in PREFERRED_DRIVERS:
        if d in installed:
            return d
    raise RuntimeError(f"No SQL Server ODBC driver found. Installed drivers: {installed}")


def get_engine(database=DEFAULT_DATABASE):
    """Return a SQLAlchemy engine for the given database."""
    conn_str = (
        f"DRIVER={{{_pick_driver()}}};SERVER={SERVER};DATABASE={database};"
        "Trusted_Connection=yes;TrustServerCertificate=yes"
    )
    return create_engine("mssql+pyodbc:///?odbc_connect=" + quote_plus(conn_str),
                         fast_executemany=True)


def test_connection(database=DEFAULT_DATABASE):
    """Connect, run a few checks, and print the result. Returns True if it worked."""
    try:
        with get_engine(database).connect() as conn:
            db = conn.execute(text("SELECT DB_NAME()")).scalar()
            tables = conn.execute(text("SELECT COUNT(*) FROM sys.tables")).scalar()
            print(f"Connected to server {SERVER}, database '{db}' ({tables} tables).")
            rows = conn.execute(text(
                "SELECT TOP 5 * FROM dbo._catalog")).fetchall()
            print("First rows of dbo._catalog:")
            for r in rows:
                print("  ", tuple(r))
        return True
    except Exception as e:
        print(f"Connection to '{database}' FAILED: {e}")
        return False


if __name__ == "__main__":
    test_connection()
