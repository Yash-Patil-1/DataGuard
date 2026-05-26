"""
DataGuard — Database Connectors

Load data from external sources: PostgreSQL, Snowflake, SQLite, and CSV.
All connectors follow a common interface for drop-in use with the pipeline.

Usage:
    from src.connectors import get_connector, list_sources

    # Auto-detect by source name:
    conn = get_connector("postgresql://host:5432/mydb")
    df = conn.query("SELECT * FROM orders WHERE date >= '2026-01-01'")

    # Or use specific connector:
    from src.connectors import PostgreSQLConnector
    conn = PostgreSQLConnector(host="localhost", dbname="mydb", ...)
    df = conn.read_table("orders")
"""

import os
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse


# ═══════════════════════════════════════════════════════════
# BASE CONNECTOR
# ═══════════════════════════════════════════════════════════

class BaseConnector:
    """Abstract base for all data connectors."""

    name = "base"

    def test_connection(self) -> bool:
        """Verify connectivity. Return True if reachable."""
        raise NotImplementedError

    def read_table(self, table: str, **kwargs) -> "pd.DataFrame":
        """Read an entire table into a DataFrame."""
        raise NotImplementedError

    def query(self, sql: str, **kwargs) -> "pd.DataFrame":
        """Run a raw SQL query and return results."""
        raise NotImplementedError

    def get_schema(self, table: str) -> List[Dict[str, Any]]:
        """Inspect column names, types, nullability for a table."""
        raise NotImplementedError

    def list_tables(self) -> List[str]:
        """List available table/view names."""
        raise NotImplementedError

    def close(self):
        """Release any held resources."""
        pass


# ═══════════════════════════════════════════════════════════
# CSV CONNECTOR (built-in, no extra deps)
# ═══════════════════════════════════════════════════════════

class CSVConnector(BaseConnector):
    """Read data from local CSV files."""

    name = "csv"

    def __init__(self, path: str, **kwargs):
        self.path = path
        self.kwargs = kwargs

    def test_connection(self) -> bool:
        return os.path.exists(self.path)

    def read_table(self, table: str = None, **kwargs) -> "pd.DataFrame":
        import pandas as pd
        return pd.read_csv(self.path, **{**self.kwargs, **kwargs})

    def query(self, sql: str = None, **kwargs) -> "pd.DataFrame":
        # CSV doesn't support SQL natively; just read the file
        return self.read_table(**kwargs)

    def get_schema(self, table: str = None) -> List[Dict[str, Any]]:
        import pandas as pd
        df = pd.read_csv(self.path, nrows=100)
        schema = []
        for col in df.columns:
            schema.append({
                "column_name": col,
                "dtype": str(df[col].dtype),
                "nullable": df[col].isnull().any(),
                "sample": str(df[col].dropna().iloc[0]) if len(df[col].dropna()) > 0 else None,
            })
        return schema

    def list_tables(self) -> List[str]:
        return [os.path.basename(self.path)]


# ═══════════════════════════════════════════════════════════
# SQLITE CONNECTOR (stdlib)
# ═══════════════════════════════════════════════════════════

class SQLiteConnector(BaseConnector):
    """Read data from SQLite databases. Uses sqlite3 from stdlib."""

    name = "sqlite"

    def __init__(self, path: str, **kwargs):
        import sqlite3
        self.path = path
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row

    def test_connection(self) -> bool:
        try:
            self._conn.cursor().execute("SELECT 1")
            return True
        except Exception:
            return False

    def read_table(self, table: str, **kwargs) -> "pd.DataFrame":
        import pandas as pd
        limit = kwargs.pop("limit", None)
        sql = f'SELECT * FROM "{table}"'
        if limit:
            sql += f" LIMIT {limit}"
        return pd.read_sql_query(sql, self._conn, **kwargs)

    def query(self, sql: str, **kwargs) -> "pd.DataFrame":
        import pandas as pd
        return pd.read_sql_query(sql, self._conn, **kwargs)

    def get_schema(self, table: str) -> List[Dict[str, Any]]:
        cursor = self._conn.execute(f'PRAGMA table_info("{table}")')
        schema = []
        for row in cursor.fetchall():
            schema.append({
                "column_name": row["name"],
                "dtype": row["type"],
                "nullable": not row["notnull"],
                "default": row["dflt_value"],
            })
        return schema

    def list_tables(self) -> List[str]:
        cursor = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        return [row["name"] for row in cursor.fetchall()]

    def close(self):
        self._conn.close()


# ═══════════════════════════════════════════════════════════
# POSTGRESQL CONNECTOR (requires psycopg2 or pg8000)
# ═══════════════════════════════════════════════════════════

class PostgreSQLConnector(BaseConnector):
    """Read data from PostgreSQL databases.

    Requires either 'psycopg2' or 'pg8000' to be installed.

    Connection via DSN string:
        postgresql://user:pass@host:5432/dbname?schema=public

    Or via keyword arguments:
        PostgreSQLConnector(host="localhost", dbname="mydb", user="...", password="...")
    """

    name = "postgresql"

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        dbname: str = None,
        user: str = None,
        password: str = None,
        schema: str = "public",
        dsn: str = None,
        **kwargs,
    ):
        self.host = host
        self.port = port
        self.dbname = dbname
        self.user = user
        self.password = password
        self.schema = schema
        self._conn = None
        self._driver = None

        # Parse DSN if provided
        if dsn:
            self._parse_dsn(dsn)

    def _parse_dsn(self, dsn: str):
        parsed = urlparse(dsn)
        self.host = parsed.hostname or self.host
        self.port = parsed.port or self.port
        self.dbname = parsed.path.lstrip("/") if parsed.path else self.dbname
        self.user = parsed.username or self.user
        self.password = parsed.password or self.password
        # Extract schema from query params
        if parsed.query:
            params = dict(qc.split("=") for qc in parsed.query.split("&") if "=" in qc)
            self.schema = params.get("schema", self.schema)

    def _connect(self):
        if self._conn is not None:
            return

        # Try psycopg2 first, fall back to pg8000
        try:
            import psycopg2
            self._driver = "psycopg2"
            self._conn = psycopg2.connect(
                host=self.host,
                port=self.port,
                dbname=self.dbname,
                user=self.user,
                password=self.password,
                options=f"-c search_path={self.schema}",
            )
        except ImportError:
            try:
                import pg8000
                self._driver = "pg8000"
                self._conn = pg8000.connect(
                    host=self.host,
                    port=self.port,
                    database=self.dbname,
                    user=self.user,
                    password=self.password,
                )
            except ImportError:
                raise ImportError(
                    "PostgreSQL support requires psycopg2 or pg8000. "
                    "Install: pip install dataguard[postgresql]"
                )

    def test_connection(self) -> bool:
        try:
            self._connect()
            cursor = self._conn.cursor()
            cursor.execute("SELECT 1")
            return True
        except Exception:
            return False

    def read_table(self, table: str, **kwargs) -> "pd.DataFrame":
        import pandas as pd
        self._connect()
        sql = f'SELECT * FROM "{self.schema}"."{table}"'
        limit = kwargs.pop("limit", None)
        if limit:
            sql += f" LIMIT {limit}"
        return pd.read_sql_query(sql, self._conn, **kwargs)

    def query(self, sql: str, **kwargs) -> "pd.DataFrame":
        import pandas as pd
        self._connect()
        return pd.read_sql_query(sql, self._conn, **kwargs)

    def get_schema(self, table: str) -> List[Dict[str, Any]]:
        self._connect()
        cursor = self._conn.cursor()
        cursor.execute(
            f"""
            SELECT column_name, data_type, is_nullable, character_maximum_length
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
            """,
            (self.schema, table),
        )
        schema = []
        for row in cursor.fetchall():
            schema.append({
                "column_name": row[0],
                "dtype": row[1],
                "nullable": row[2] == "YES",
                "max_length": row[3],
            })
        return schema

    def list_tables(self) -> List[str]:
        self._connect()
        cursor = self._conn.cursor()
        cursor.execute(
            f"""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """,
            (self.schema,),
        )
        return [row[0] for row in cursor.fetchall()]

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None


# ═══════════════════════════════════════════════════════════
# SNOWFLAKE CONNECTOR (requires snowflake-connector-python)
# ═══════════════════════════════════════════════════════════

class SnowflakeConnector(BaseConnector):
    """Read data from Snowflake data warehouses.

    Requires 'snowflake-connector-python' to be installed.

    Usage:
        conn = SnowflakeConnector(
            account="xy12345.us-east-1",
            user="analyst",
            password="...",
            warehouse="COMPUTE_WH",
            database="PROD",
            schema="PUBLIC",
        )
        df = conn.read_table("ORDERS")

    Or via DSN:
        conn = get_connector("snowflake://user:pass@xy12345/ANALYTICS/PUBLIC?warehouse=COMPUTE_WH")
    """

    name = "snowflake"

    def __init__(
        self,
        account: str = None,
        user: str = None,
        password: str = None,
        warehouse: str = None,
        database: str = None,
        schema: str = "PUBLIC",
        role: str = None,
        dsn: str = None,
        **kwargs,
    ):
        self.account = account
        self.user = user
        self.password = password
        self.warehouse = warehouse
        self.database = database
        self.schema = schema
        self.role = role
        self._conn = None

        # Parse DSN if provided
        if dsn:
            self._parse_dsn(dsn)

    def _parse_dsn(self, dsn: str):
        parsed = urlparse(dsn)
        self.user = parsed.username or self.user
        self.password = parsed.password or self.password
        # netloc = account
        self.account = parsed.hostname or self.account
        # path = /database/schema
        parts = parsed.path.strip("/").split("/")
        if len(parts) >= 1:
            self.database = parts[0]
        if len(parts) >= 2:
            self.schema = parts[1]
        # query params
        if parsed.query:
            params = dict(qc.split("=") for qc in parsed.query.split("&") if "=" in qc)
            self.warehouse = params.get("warehouse", self.warehouse)
            self.role = params.get("role", self.role)

    def _connect(self):
        if self._conn is not None:
            return
        try:
            import snowflake.connector
        except ImportError:
            raise ImportError(
                "Snowflake support requires snowflake-connector-python. "
                "Install: pip install dataguard[snowflake]"
            )

        self._conn = snowflake.connector.connect(
            account=self.account,
            user=self.user,
            password=self.password,
            warehouse=self.warehouse,
            database=self.database,
            schema=self.schema,
            role=self.role,
        )

    def test_connection(self) -> bool:
        try:
            self._connect()
            cursor = self._conn.cursor()
            cursor.execute("SELECT 1")
            return True
        except Exception:
            return False

    def read_table(self, table: str, **kwargs) -> "pd.DataFrame":
        import pandas as pd
        self._connect()
        sql = f'SELECT * FROM "{self.database}"."{self.schema}"."{table}"'
        limit = kwargs.pop("limit", None)
        if limit:
            sql += f" LIMIT {limit}"
        return pd.read_sql_query(sql, self._conn, **kwargs)

    def query(self, sql: str, **kwargs) -> "pd.DataFrame":
        import pandas as pd
        self._connect()
        return pd.read_sql_query(sql, self._conn, **kwargs)

    def get_schema(self, table: str) -> List[Dict[str, Any]]:
        self._connect()
        cursor = self._conn.cursor()
        cursor.execute(
            f"""
            SELECT column_name, data_type, is_nullable, character_maximum_length
            FROM information_schema.columns
            WHERE table_catalog = %s AND table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
            """,
            (self.database.upper(), self.schema.upper(), table.upper()),
        )
        schema = []
        for row in cursor.fetchall():
            schema.append({
                "column_name": row[0],
                "dtype": row[1],
                "nullable": row[2] == "YES",
                "max_length": row[3],
            })
        return schema

    def list_tables(self) -> List[str]:
        self._connect()
        cursor = self._conn.cursor()
        cursor.execute(
            f"""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_catalog = %s AND table_schema = %s AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """,
            (self.database.upper(), self.schema.upper()),
        )
        return [row[0] for row in cursor.fetchall()]

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None


# ═══════════════════════════════════════════════════════════
# CONNECTOR FACTORY
# ═══════════════════════════════════════════════════════════

CONNECTOR_REGISTRY = {
    "csv": CSVConnector,
    "sqlite": SQLiteConnector,
    "postgresql": PostgreSQLConnector,
    "postgres": PostgreSQLConnector,
    "pg": PostgreSQLConnector,
    "snowflake": SnowflakeConnector,
}

# Aliases for connection URI schemes
SCHEME_MAP = {
    "csv": "csv",
    "sqlite": "sqlite",
    "sqlite3": "sqlite",
    "postgresql": "postgresql",
    "postgres": "postgresql",
    "pg": "postgresql",
    "snowflake": "snowflake",
}


def get_connector(source: str, **kwargs) -> BaseConnector:
    """Create a connector from a source string or connection URI.

    Args:
        source: Connection URI (e.g., 'postgresql://user:pass@host/db')
                or source type name (e.g., 'csv', 'sqlite', 'postgresql', 'snowflake')
        **kwargs: Additional keyword arguments passed to the connector constructor.

    Returns:
        A BaseConnector instance.

    Raises:
        ValueError: If the source type is unknown.
    """
    # Parse as URI if it contains ://
    if "://" in source:
        parsed = urlparse(source)
        scheme = parsed.scheme.lower()
        connector_type = SCHEME_MAP.get(scheme)
        if connector_type is None:
            raise ValueError(
                f"Unknown URI scheme '{scheme}'. Supported: "
                f"{', '.join(SCHEME_MAP.keys())}"
            )
        # Pass the full DSN to the connector
        cls = CONNECTOR_REGISTRY[connector_type]
        return cls(dsn=source, **kwargs)

    # Otherwise treat as a connector type name
    source_lower = source.lower()
    if source_lower in CONNECTOR_REGISTRY:
        cls = CONNECTOR_REGISTRY[source_lower]
        return cls(**kwargs)

    # Check if it's a file path
    if os.path.exists(source):
        ext = os.path.splitext(source)[1].lower()
        if ext == ".csv":
            return CSVConnector(path=source, **kwargs)
        elif ext in (".db", ".sqlite", ".sqlite3"):
            return SQLiteConnector(path=source, **kwargs)

    raise ValueError(
        f"Unknown source '{source}'. Supported types: "
        f"{', '.join(CONNECTOR_REGISTRY.keys())}. "
        f"For files, use a .csv, .db, .sqlite, or .sqlite3 path."
    )


def list_sources() -> Dict[str, str]:
    """Return available connector types with descriptions."""
    return {
        "csv": "Local CSV files (no extra deps)",
        "sqlite": "SQLite databases (stdlib)",
        "postgresql": "PostgreSQL (requires psycopg2 or pg8000)",
        "snowflake": "Snowflake (requires snowflake-connector-python)",
    }


# ═══════════════════════════════════════════════════════════
# CONVENIENCE: load from any source into pipeline format
# ═══════════════════════════════════════════════════════════

def load_dataframe(source: str, table_or_path: str = None, **kwargs) -> "pd.DataFrame":
    """Load a DataFrame from any supported source.

    This is the main entry point for the pipeline to use external data.

    Args:
        source: Connection URI or type name
        table_or_path: Table name (for DB sources) or file path (for file sources).
                       If None, attempts auto-detection.
        **kwargs: Additional query args (e.g., limit=1000, where="date > '2026-01-01'")

    Returns:
        pandas DataFrame

    Examples:
        df = load_dataframe("csv", "data/orders.csv")
        df = load_dataframe("postgresql://user:pass@localhost/db", "orders")
        df = load_dataframe("snowflake://user:pass@xy12345/ANALYTICS/PUBLIC", "ORDERS")
    """
    conn = get_connector(source, **kwargs)
    try:
        if table_or_path:
            df = conn.read_table(table_or_path, **kwargs)
        else:
            # For file-based connectors, read without table name
            df = conn.read_table(**kwargs)
        return df
    finally:
        conn.close()


def source_to_connector_args(source: str) -> Dict[str, Any]:
    """Convert a source type name to a dict of connector kwargs for config files.

    Useful for YAML-based pipeline configuration.
    """
    mapping = {
        "csv": {"type": "csv", "path": "data/all_orders_combined.csv"},
        "sqlite": {"type": "sqlite", "path": "data/pipeline.db"},
        "postgresql": {
            "type": "postgresql",
            "host": "${PG_HOST}",
            "dbname": "${PG_DB}",
            "user": "${PG_USER}",
            "password": "${PG_PASSWORD}",
        },
        "snowflake": {
            "type": "snowflake",
            "account": "${SNOWFLAKE_ACCOUNT}",
            "user": "${SNOWFLAKE_USER}",
            "password": "${SNOWFLAKE_PASSWORD}",
            "database": "${SNOWFLAKE_DATABASE}",
        },
    }
    return mapping.get(source, {"type": source})


# Quick test
if __name__ == "__main__":
    print("=" * 60)
    print("  DataGuard — Connectors")
    print("=" * 60)
    print(f"\n  Available sources:")
    for name, desc in list_sources().items():
        print(f"    {name:15s} — {desc}")
    print(f"\n  Usage:")
    print(f"    from src.connectors import get_connector, load_dataframe")
    print(f"    df = load_dataframe('csv', 'data/orders.csv')")
    print(f"    df = load_dataframe('postgresql://user:pass@localhost/db', 'orders')")
    print(f"    df = load_dataframe('snowflake://user:pass@acct/DB/SCHEMA', 'TABLE')")
    print("=" * 60)
