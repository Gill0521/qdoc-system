from database import get_db_connection, print_db_settings_for_check

print_db_settings_for_check()
try:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT DATABASE(), VERSION()")
    db_name, version = cur.fetchone()
    print("Connection: SUCCESS")
    print("Database:", db_name)
    print("MySQL version:", version)
    cur.execute("SHOW TABLES")
    print("Tables:", ", ".join(row[0] for row in cur.fetchall()))
    cur.close()
    conn.close()
except Exception as exc:
    print("Connection: FAILED")
    print(type(exc).__name__ + ":", exc)
