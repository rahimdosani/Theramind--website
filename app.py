from flask import Flask, render_template, request, jsonify, session, Response
from flask_cors import CORS
import sqlite3
import datetime
import json
import os
import re
import requests
from dotenv import load_dotenv
import time
import random

# -------------------- Env --------------------
load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "theramind-secret-key")

# -------------------- App --------------------
app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY
CORS(app)

# ======================================================
# Utils: DB
# ======================================================
CONV_DB = "conversations.db"
JOURNAL_DB = "journal.db"
MOOD_DB = "mood_data.db"

def connect(db_path):
    return sqlite3.connect(db_path, check_same_thread=False)

def setup_conversations_db():
    conn = connect(CONV_DB)
    c = conn.cursor()
    c.execute(
        """CREATE TABLE IF NOT EXISTS conversations (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               title TEXT NOT NULL,
               history TEXT NOT NULL,
               created_at TEXT NOT NULL
           )"""
    )
    conn.commit()
    conn.close()

def setup_databases():
    # mood_data
    conn = connect(MOOD_DB)
    c = conn.cursor()
    c.execute(
        """CREATE TABLE IF NOT EXISTS mood_logs (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               date TEXT,
               mood TEXT,
               message TEXT
           )"""
    )
    conn.commit()
    conn.close()

    # journal
    conn = connect(JOURNAL_DB)
    c = conn.cursor()
    c.execute(
        """CREATE TABLE IF NOT EXISTS journal_entries (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               date TEXT,
               content TEXT
           )"""
    )
    conn.commit()
    conn.close()

    setup_conversations_db()

# ======================================================
# Utils: Session persistence
# ======================================================
def save_current_session(history):
    conn = connect(CONV_DB)
    c = conn.cursor()
    c.execute('DELETE FROM conversations WHERE title = "__current__"')
    c.execute(
        "INSERT INTO conversations (title, history, created_at) VALUES (?, ?, ?)",
        ("__current__", json.dumps(history), now()),
    )
    conn.commit()
    conn.close()

def load_current_session():
    conn = connect(CONV_DB)
    c = conn.cursor()
    c.execute(
        'SELECT history FROM conversations WHERE title = "__current__" ORDER BY created_at DESC LIMIT 1'
    )
    row = c.fetchone()
    conn.close()
    return json.loads(row[0]) if row else []

def clear_current_session():
    conn = connect(CONV_DB)
    c = conn.cursor()
    c.execute('DELETE FROM conversations WHERE title = "__current__"')
    conn.commit()
    conn.close()

# ======================================================
# Utils: Time
# ======================================================
def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ======================================================
# Utils: Text safety & heuristics
# ======================================================
_GIBBERISH_RE = re.compile(r"^[^a-zA-Z0-9]*$")

def looks_like_gibberish(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    if _GIBBERISH_RE.match(t):
        return True
    if len(t) <= 2:
        return True
    if len(t) >= 12 and " " not in t:
        letters = re.sub(r"[^a-zA-Z]", "", t)
        if letters:
            vowels = re.findall(r"[aeiouAEIOU]", letters)
            if len(vowels) / max(1, len(letters)) < 0.15:
                return True
        if re.search(r"(.)\1{4,}", t):
            return True
    symbols = re.findall(r"[^a-zA-Z0-9\s]", t)
    if len(symbols) >= 6 and len(symbols) > (len(t) * 0.3):
        return True
    return False

def graceful_gibberish_reply():
    return (
        "Hmm, that looks a bit like a typo or test. No worries — I'm here to help. "
        "Tell me what's on your mind, or we can do a short 1-minute breathing reset. 💙"
    )

def safe_trim(text: str, max_len: int = 2000) -> str:
    text = (text or "").strip()
    if len(text) > max_len:
        text = text[:max_len]
    return text

# ======================================================
# Utils: Model logic & empathy
# ======================================================
def remove_ai_language(reply):
    blacklist = [
        "as an AI", "as an assistant", "as a chatbot",
        "i'm just a bot", "i'm not human", "i am a virtual assistant",
        "as a language model", "I don't have emotions", "I'm not a human"
    ]
    out = reply or ""
    for phrase in blacklist:
        out = out.replace(phrase, "")
    return out.strip()

def basic_empathy_reply(message):
    msg = (message or "").lower()
    if any(word in msg for word in ['sad', 'upset', 'down', 'depressed']):
        return "I'm really sorry you're feeling this way. You're not alone — I'm right here. Would you like to write about it in your journal or try a 1-minute breathing reset? 💙"
    if any(word in msg for word in ['happy', 'excited', 'great']):
        return "That's wonderful! Celebrate this moment! Maybe jot it down in your journal to remember it. 😊"
    if any(word in msg for word in ['anxious', 'panic', 'nervous']):
        return "It’s okay to feel overwhelmed. Want a quick guided breathing session or grounding exercise?"
    if any(word in msg for word in ['angry', 'mad', 'furious']):
        return "I hear you — anger is valid. Let’s breathe together or write down what’s bothering you."
    if any(word in msg for word in ['lonely', 'alone']):
        return "Please know you're not alone. I'm here, and I care. Maybe writing your feelings down could help?"
    return None

def generate_reply_with_context(chat_history):
    context_messages = [m for m in chat_history[-10:] if m['role'] in ['user', 'model']]
    last_user_message = next((m['content'] for m in reversed(chat_history) if m.get('role') == 'user'), '')

    if looks_like_gibberish(last_user_message):
        return graceful_gibberish_reply()

    fallback = basic_empathy_reply(last_user_message)
    if fallback:
        return fallback

    if not OPENROUTER_API_KEY:
        return (
            "Thanks for sharing. I’m here with you. "
            "Would you like to jot down a few thoughts, or try a short breathing pause together?"
        )

    try:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}

        messages = []
        for msg in context_messages:
            role = msg['role']
            if role == "model":  # Convert to 'assistant' for OpenRouter
                role = "assistant"
            messages.append({"role": role, "content": safe_trim(msg['content'])})

        system_prompt = {
            "role": "system",
            "content": (
                "You're Theramind, a warm, compassionate mental health companion. "
                "Speak like a caring friend. Suggest journaling, breathing, grounding, or talking to someone. "
                "Do NOT mention AI or being a chatbot. Keep it concise, hopeful, and human-like."
            )
        }

        payload = {
            "model": "gpt-4o-mini",
            "messages": [system_prompt] + messages,
            "temperature": 0.7,
            "top_p": 0.9
        }

        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        resp.raise_for_status()
        result = resp.json()

        if "choices" in result and result["choices"]:
            text = result["choices"][0]["message"]["content"]
            return remove_ai_language(text) or graceful_gibberish_reply()

        fallbacks = [
            "I'm here to listen. Want to share a bit more?",
            "Take your time. You can write down your thoughts or try a short breathing exercise.",
            "I’m with you. Sometimes jotting down feelings can help."
        ]
        return random.choice(fallbacks)

    except Exception as e:
        print("❌ OpenRouter Error:", e)
        fallbacks = [
            "I'm here for you, something went wrong. Want to try again in a moment?",
            "Oops, I couldn’t form a response just now. Take a deep breath, and we can continue.",
            "I’m listening — sometimes it takes a second. Shall we continue?"
        ]
        return random.choice(fallbacks)

# ======================================================
# Routes & Session
# ======================================================
@app.before_request
def ensure_session_history():
    if 'history' not in session:
        session['history'] = []

    # Rate limiting for /chat
    if 'last_request' not in session:
        session['last_request'] = 0
    if request.endpoint == 'chat':
        now_time = time.time()
        if now_time - session['last_request'] < 1.5:
            return jsonify({'reply': "Whoa! Slow down a bit. Take a breath and try again."})
        session['last_request'] = now_time

@app.route('/')
def home():
    session['welcome_shown'] = False
    return render_template('home.html')

@app.route('/index')
def index():
    if not session.get('welcome_shown'):
        session['welcome_shown'] = True
        return render_template('index.html', show_welcome=True)
    return render_template('index.html', show_welcome=False)

@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json(silent=True) or {}
    message = safe_trim(data.get('message', ''))
    session['history'].append({"role": "user", "content": message})
    reply = generate_reply_with_context(session['history'])
    session['history'].append({"role": "model", "content": reply})
    save_current_session(session['history'])
    return jsonify({'reply': reply})

@app.route('/reset_session')
def reset_session():
    session['history'] = []
    clear_current_session()
    return jsonify({'status': 'reset'})

@app.route('/get_current_session')
def get_current_session():
    history = load_current_session()
    session['history'] = history
    return jsonify(history)

# -------- Conversations CRUD --------
@app.route('/save_conversation', methods=['POST'])
def save_conversation():
    data = request.get_json(silent=True) or {}
    title = safe_trim(data.get('title', 'Untitled'), 120) or "Untitled"
    history = session.get('history', [])
    created_at = now()
    if not history:
        return jsonify({'status': 'failed', 'message': 'No history to save'}), 400
    conn = connect(CONV_DB)
    c = conn.cursor()
    c.execute("INSERT INTO conversations (title, history, created_at) VALUES (?, ?, ?)",
              (title, json.dumps(history), created_at))
    chat_id = c.lastrowid
    conn.commit()
    conn.close()
    return jsonify({'status': 'success', 'id': chat_id})

@app.route('/get_conversations')
def get_conversations():
    conn = connect(CONV_DB)
    c = conn.cursor()
    c.execute('SELECT id, title, created_at FROM conversations WHERE title != "__current__" ORDER BY created_at DESC')
    rows = c.fetchall()
    conn.close()
    return jsonify([{'id': row[0], 'title': row[1], 'created_at': row[2]} for row in rows])

@app.route('/load_conversation/<int:chat_id>')
def load_conversation(chat_id):
    conn = connect(CONV_DB)
    c = conn.cursor()
    c.execute('SELECT history FROM conversations WHERE id = ?', (chat_id,))
    row = c.fetchone()
    conn.close()
    if row:
        history = json.loads(row[0])
        session['history'] = history
        return jsonify(history)
    return jsonify([])

@app.route('/delete_conversation/<int:chat_id>', methods=['DELETE'])
def delete_conversation(chat_id):
    conn = connect(CONV_DB)
    c = conn.cursor()
    c.execute('DELETE FROM conversations WHERE id = ?', (chat_id,))
    conn.commit()
    conn.close()
    return jsonify({'status': 'deleted'})

@app.route('/rename_conversation/<int:chat_id>', methods=['POST'])
def rename_conversation(chat_id):
    data = request.get_json(silent=True) or {}
    new_title = safe_trim(data.get('title', ''), 120)
    if not new_title:
        return jsonify({'status': 'failed', 'message': 'No title provided'}), 400
    conn = connect(CONV_DB)
    c = conn.cursor()
    c.execute('UPDATE conversations SET title = ? WHERE id = ?', (new_title, chat_id))
    conn.commit()
    conn.close()
    return jsonify({'status': 'renamed'})

# -------- Journaling & other pages --------
@app.route('/journaling', methods=['GET', 'POST'])
def journaling():
    saved = False
    if request.method == 'POST':
        entry = safe_trim(request.form.get('entry', ''), 5000)
        if entry:
            conn = connect(JOURNAL_DB)
            c = conn.cursor()
            c.execute("INSERT INTO journal_entries (date, content) VALUES (?, ?)", (now(), entry))
            conn.commit()
            conn.close()
            saved = True
    return render_template('journaling.html', saved=saved)

@app.route('/search_journals', methods=['GET'])
def search_journals():
    query = request.args.get('q', '').strip()
    conn = connect(JOURNAL_DB)
    c = conn.cursor()
    if query:
        c.execute("SELECT date, content FROM journal_entries WHERE content LIKE ? ORDER BY id DESC", (f"%{query}%",))
    else:
        c.execute("SELECT date, content FROM journal_entries ORDER BY id DESC")
    results = c.fetchall()
    conn.close()
    return jsonify(results)

@app.route('/export_journal')
def export_journal():
    conn = connect(JOURNAL_DB)
    c = conn.cursor()
    c.execute("SELECT date, content FROM journal_entries ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    
    text_data = "\n\n".join([f"{row[0]}:\n{row[1]}" for row in rows])
    
    return Response(
        text_data,
        mimetype="text/plain",
        headers={"Content-Disposition": "attachment;filename=journal.txt"}
    )

@app.route('/export_chat')
def export_chat():
    history = session.get('history', [])
    text_data = "\n\n".join([f"{m['role'].capitalize()}: {m['content']}" for m in history])
    return Response(
        text_data,
        mimetype="text/plain",
        headers={"Content-Disposition": "attachment;filename=chat_history.txt"}
    )

@app.route('/breathing')
def breathing():
    return render_template('breathing.html')

@app.route('/history')
def history():
    conn1 = connect(MOOD_DB)
    c1 = conn1.cursor()
    c1.execute('SELECT date, mood, message FROM mood_logs ORDER BY id DESC')
    mood_logs = c1.fetchall()
    conn1.close()

    conn2 = connect(JOURNAL_DB)
    c2 = conn2.cursor()
    c2.execute('SELECT date, content FROM journal_entries ORDER BY id DESC')
    journal_entries = c2.fetchall()
    conn2.close()

    return render_template('history.html', mood_logs=mood_logs, journal_entries=journal_entries)

@app.route('/pick-a-peace')
def pick_a_peace():
    return render_template('pick_a_peace.html')

@app.route('/calm-corner')
def calm_corner():
    return render_template("calm-corner.html")

@app.route('/ebooks')
def ebooks():
    return render_template("ebooks.html")

# -------------------- Run --------------------
if __name__ == '__main__':
    setup_databases()
    app.run(debug=True)
