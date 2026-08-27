import os
import sqlite3
import psycopg

DATABASE_URL = os.environ["DATABASE_URL"]

TABLES = [
    ("users.db", "users", [
        "id", "username", "email", "password_hash", "display_name",
        "intent", "email_verified", "is_admin", "created_at",
        "auth_provider", "last_login"
    ]),
    ("users.db", "user_profile", ["user_id", "goals"]),
    ("users.db", "email_otps", ["id", "email", "otp", "expires_at"]),
    ("users.db", "admin_logs", [
        "id", "admin_id", "action", "target_user_id", "timestamp"
    ]),
    ("conversations.db", "conversations", [
        "id", "title", "history", "created_at", "user_id"
    ]),
    ("conversations.db", "memories", [
        "id", "conv_id", "summary", "updated_at", "user_id"
    ]),
    ("journal.db", "journal_entries", [
        "id", "date", "content", "user_id", "title", "mood", "tags"
    ]),
    ("mood_data.db", "mood_logs", [
        "id", "mood", "message", "date", "user_id"
    ]),
]


def read_rows(db_file, table):
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def main():
    print("========================================")
    print("Theramind SQLite -> PostgreSQL Migration")
    print("========================================")

    all_data = []

    for db_file, table, columns in TABLES:
        rows = read_rows(db_file, table)
        all_data.append((table, columns, rows))
        print(f"{table}: {len(rows)} rows found")

    print("\nConnecting to PostgreSQL...")

    with psycopg.connect(DATABASE_URL) as pg:

        for table, columns, rows in all_data:
            if not rows:
                print(f"  {table}: skipped (0 rows)")
                continue

            column_sql = ", ".join(columns)
            placeholders = ", ".join(["%s"] * len(columns))

            query = f"""
                INSERT INTO {table} ({column_sql})
                VALUES ({placeholders})
                ON CONFLICT DO NOTHING
            """

            for row in rows:
                pg.execute(
                    query,
                    [row[column] for column in columns]
                )

            print(f"  {table}: migrated {len(rows)} rows")

        # Reset identity sequences so future INSERTs get IDs
        # after the imported records.
        for table in [
            "users",
            "email_otps",
            "admin_logs",
            "conversations",
            "memories",
            "journal_entries",
            "mood_logs",
        ]:
            pg.execute(
                f"""
                SELECT setval(
                    pg_get_serial_sequence(%s, 'id'),
                    COALESCE(MAX(id), 1),
                    MAX(id) IS NOT NULL
                )
                FROM {table}
                """,
                (table,)
            )

        pg.commit()

    print("\n========================================")
    print("SUCCESS: Migration completed")
    print("========================================")


if __name__ == "__main__":
    main()
