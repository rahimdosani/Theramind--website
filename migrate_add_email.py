# migrate_add_email.py
import sqlite3, os
DB = os.path.join(os.path.dirname(__file__), "users.db")
conn = sqlite3.connect(DB)
c = conn.cursor()
# Add email column if not present
try:
    c.execute("ALTER TABLE users ADD COLUMN email TEXT")
    print("Added column: email")
except Exception as e:
    print("email column may already exist:", e)
# Add email_verified column
try:
    c.execute("ALTER TABLE users ADD COLUMN email_verified INTEGER DEFAULT 0")
    print("Added column: email_verified")
except Exception as e:
    print("email_verified column may already exist:", e)
# make sure email has an index/uniqueness - SQLite cannot add unique constraint easily,
# but we can create an index (unique) which will fail if duplicates exist.
try:
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email)")
    print("Unique index on email created (or already exists).")
except Exception as e:
    print("Could not create unique index:", e)

conn.commit()
conn.close()
print("Migration finished.")
