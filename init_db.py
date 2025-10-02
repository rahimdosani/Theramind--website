import sqlite3

# Create mood_data.db and mood_logs table
conn1 = sqlite3.connect('mood_data.db')
c1 = conn1.cursor()
c1.execute('''
    CREATE TABLE IF NOT EXISTS mood_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mood TEXT NOT NULL,
        message TEXT,
        date TEXT NOT NULL
    )
''')
conn1.commit()
conn1.close()

# Create journal.db and journal_entries table
conn2 = sqlite3.connect('journal.db')
c2 = conn2.cursor()
c2.execute('''
    CREATE TABLE IF NOT EXISTS journal_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content TEXT NOT NULL,
        date TEXT NOT NULL
    )
''')
conn2.commit()
conn2.close()

print("✅ Databases and tables created successfully.")
