import os
import tempfile
from pathlib import Path

import mysql.connector
from mysql.connector import pooling
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH, override=False)

_connection_pool = None


def get_aiven_ca_path():
    ca_content = os.getenv("DB_SSL_CA_CONTENT", "").strip()

    if not ca_content:
        return None

    ca_path = Path(tempfile.gettempdir()) / "aiven-ca.pem"

    with open(ca_path, "w", encoding="utf-8") as file:
        file.write(ca_content.replace("\\n", "\n"))

    return str(ca_path)


def build_db_config():
    db_host = os.getenv("DB_HOST", "").strip()
    db_port = os.getenv("DB_PORT", "3306").strip()
    db_user = os.getenv("DB_USER", "").strip()
    db_password = os.getenv("DB_PASSWORD", "")
    db_name = os.getenv("DB_NAME", "").strip()

    if not db_host:
        raise RuntimeError("DB_HOST is missing. Check Render Environment Variables.")

    if not db_user:
        raise RuntimeError("DB_USER is missing. Check Render Environment Variables.")

    if not db_password:
        raise RuntimeError("DB_PASSWORD is missing. Check Render Environment Variables.")

    if not db_name:
        raise RuntimeError("DB_NAME is missing. Check Render Environment Variables.")

    config = {
        "host": db_host,
        "port": int(db_port),
        "user": db_user,
        "password": db_password,
        "database": db_name,
        "connection_timeout": 10,
        "autocommit": False,
    }

    ca_path = get_aiven_ca_path()

    if ca_path:
        config["ssl_ca"] = ca_path
        config["ssl_verify_cert"] = True

    return config


def get_db_connection():
    global _connection_pool

    if _connection_pool is None:
        _connection_pool = pooling.MySQLConnectionPool(
            pool_name="qdoc_pool",
            pool_size=3,
            pool_reset_session=True,
            **build_db_config()
        )

    return _connection_pool.get_connection()


def print_db_settings_for_check():
    print("ENV file:", ENV_PATH)
    print("ENV exists:", ENV_PATH.exists())
    print("DB_HOST loaded:", "YES" if os.getenv("DB_HOST") else "NO")
    print("DB_PORT:", os.getenv("DB_PORT"))
    print("DB_USER loaded:", "YES" if os.getenv("DB_USER") else "NO")
    print("DB_NAME:", os.getenv("DB_NAME"))
    print("DB_PASSWORD loaded:", "YES" if os.getenv("DB_PASSWORD") else "NO")
    print("DB_SSL_CA_CONTENT loaded:", "YES" if os.getenv("DB_SSL_CA_CONTENT") else "NO")