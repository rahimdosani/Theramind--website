# migrate_add_google_auth.py
import sqlite3
import os

DB = os.path.join(os.path.dirname(__file__), "users.db")

conn = sqlite3.connect(DB)
c = conn.cursor()

def try_add(sql):
    try:
        c.execute(sql)
        print("✓", sql)
    except Exception as e:
        print("•", e)

try_add("ALTER TABLE users ADD COLUMN google_id TEXT")
try_add("ALTER TABLE users ADD COLUMN auth_provider TEXT DEFAULT 'local'")

conn.commit()
conn.close()
print("Google auth migration complete.")
