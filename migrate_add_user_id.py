# migrate_add_user_id.py
import sqlite3
import os

BASE_DIR = os.path.dirname(__file__)

DBS = {
    "conversations.db": [
        "ALTER TABLE conversations ADD COLUMN user_id INTEGER"
    ],
    "journal.db": [
        "ALTER TABLE journal_entries ADD COLUMN user_id INTEGER"
    ],
    "mood_data.db": [
        "ALTER TABLE mood_logs ADD COLUMN user_id INTEGER"
    ],
    "conversations.db:memories": [
        "ALTER TABLE memories ADD COLUMN user_id INTEGER"
    ]
}

def run():
    for db_name, statements in DBS.items():
        if ":" in db_name:
            db_file, _ = db_name.split(":")
        else:
            db_file = db_name

        path = os.path.join(BASE_DIR, db_file)
        if not os.path.exists(path):
            print(f"Skipping {db_file} (not found)")
            continue

        conn = sqlite3.connect(path)
        cur = conn.cursor()

        for stmt in statements:
            try:
                cur.execute(stmt)
                print(f"✓ {db_file}: {stmt}")
            except Exception as e:
                print(f"• {db_file}: {e}")

        conn.commit()
        conn.close()

if __name__ == "__main__":
    run()
