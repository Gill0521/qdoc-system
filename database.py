import os
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH, override=True)


def get_aiven_ca_path():
    ca_content = os.getenv('DB_SSL_CA_CONTENT', '').strip()

    if not ca_content:
        return None

    ca_path = '/tmp/aiven-ca.pem'

    with open(ca_path, 'w', encoding='utf-8') as file:
        file.write(ca_content.replace('\\n', '\n'))

    return ca_path


def get_db_connection():
    config = {
        'host': os.getenv('DB_HOST'),
        'port': int(os.getenv('DB_PORT', '3306')),
        'user': os.getenv('DB_USER'),
        'password': os.getenv('DB_PASSWORD'),
        'database': os.getenv('DB_NAME')
    }

    ca_path = get_aiven_ca_path()

    if ca_path:
        config['ssl_ca'] = ca_path
        config['ssl_verify_cert'] = True

    return mysql.connector.connect(**config)


def print_db_settings_for_check():
    """Used by check_db.py. It never prints the actual password."""
    print("ENV file:", ENV_PATH)
    print("ENV exists:", ENV_PATH.exists())
    print("DB_HOST:", os.getenv("DB_HOST"))
    print("DB_PORT:", os.getenv("DB_PORT"))
    print("DB_USER:", os.getenv("DB_USER"))
    print("DB_NAME:", os.getenv("DB_NAME"))
    print("DB_PASSWORD loaded:", "YES" if os.getenv("DB_PASSWORD") else "NO")
