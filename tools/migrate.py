import os
import glob
import psycopg2


def apply_migrations(conn):
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS migrations (filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ DEFAULT now())"
    )
    conn.commit()
    for path in sorted(glob.glob("db/init/*.sql")):
        name = os.path.basename(path)
        cur.execute("SELECT 1 FROM migrations WHERE filename=%s", (name,))
        if cur.fetchone():
            continue
        print(f"Applying {name}...")
        with open(path, "r", encoding="utf-8") as f:
            sql = f.read()
        cur.execute(sql)
        cur.execute("INSERT INTO migrations(filename) VALUES(%s)", (name,))
        conn.commit()
    cur.close()


if __name__ == "__main__":
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL env var required")
    conn = psycopg2.connect(dsn)
    try:
        apply_migrations(conn)
        print("All migrations applied.")
    finally:
        conn.close()

