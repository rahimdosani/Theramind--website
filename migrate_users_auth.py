# migrate_users_auth.py
import sqlite3, os, sys, time
DB = os.path.join(os.path.dirname(__file__), "users.db")
print("Migrating:", DB)
conn = sqlite3.connect(DB)
c = conn.cursor()

def safe_exec(sql):
    try:
        c.execute(sql)
        print("OK:", sql.splitlines()[0])
    except Exception as e:
        print("SKIP/ERR:", sql.splitlines()[0], "->", e)

# add columns if missing
safe_exec("ALTER TABLE users ADD COLUMN email_verified INTEGER DEFAULT 0")
safe_exec("ALTER TABLE users ADD COLUMN email TEXT")
safe_exec("ALTER TABLE users ADD COLUMN password_reset_token TEXT")
safe_exec("ALTER TABLE users ADD COLUMN password_reset_expiry INTEGER")
safe_exec("ALTER TABLE users ADD COLUMN created_at TEXT")

# create unique index on email (if emails unique)
try:
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email)")
    print("OK: create index idx_users_email")
except Exception as e:
    print("Could not create unique index:", e)

conn.commit()
conn.close()
print("Migration finished.")
