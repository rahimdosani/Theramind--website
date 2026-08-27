from werkzeug.middleware.proxy_fix import ProxyFix
import psycopg
from psycopg.rows import dict_row
import os
import re
import json
import time
import math
import random
from psycopg import errors as psycopg_errors
import logging
import datetime
import requests
from dotenv import load_dotenv
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from authlib.integrations.flask_client import OAuth
from email_utils import send_otp_email

from flask import (
    Flask, render_template, request, jsonify, session, Response, g, redirect, url_for, flash
)
from flask_cors import CORS
from flask_wtf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


# -------------------- Env --------------------
load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "theramind-secret-key")
DB_DIR = os.path.abspath(os.path.dirname(__file__))

# Admin seeding env vars
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")  # MUST be set in production


# -------------------- App --------------------
app = Flask(__name__, template_folder="templates", static_folder="static")
app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1,
    x_proto=1,
    x_host=1,
    x_port=1
)
app.secret_key = FLASK_SECRET_KEY
oauth = OAuth(app)


oauth.register(
    name="google",
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",         
    client_kwargs={
        "scope": "openid email profile"
    
    },
)

# Session & cookie security (enable Secure=True in production)
IS_PROD = os.getenv("FLASK_ENV") == "production"

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=IS_PROD,
    PERMANENT_SESSION_LIFETIME=datetime.timedelta(days=3650),
)

app.config["SESSION_REFRESH_EACH_REQUEST"] = True
app.config["SESSION_COOKIE_MAX_AGE"] = 60 * 60 * 24 * 3650



CORS(app, supports_credentials=True)

# CSRF & rate limiter
csrf = CSRFProtect()
csrf.init_app(app)
app.config["WTF_CSRF_CHECK_DEFAULT"] = False

# Generous defaults for smooth chatting
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["5000 per day", "1000 per hour"]
)
limiter.init_app(app)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("theramind")
logger.setLevel(logging.INFO)
# ======================================================
# DB paths & helpers
# ======================================================
# ======================================================
# PostgreSQL database
# ======================================================

# Compatibility labels: the existing route code passes these names to
# get_db(). All application data is now stored in one PostgreSQL database.

def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
DB_DIR = BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONV_DB = os.path.join(DB_DIR, "conversations.db")
JOURNAL_DB = os.path.join(DB_DIR, "journal.db")
MOOD_DB = os.path.join(DB_DIR, "mood_data.db")
USER_DB = os.path.join(DB_DIR, "users.db")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")


class _HybridRow:
    def __init__(self, row):
        self._row = row

    def __getitem__(self, key):
        if isinstance(key, int):
            if hasattr(self._row, "values"):
                return list(self._row.values())[key]
            return self._row[key]
        return self._row[key]

    def __iter__(self):
        return iter(self._row.values())

    def keys(self):
        return self._row.keys()

    def values(self):
        return self._row.values()

    def items(self):
        return self._row.items()

    def get(self, key, default=None):
        return self._row.get(key, default)

    def __bool__(self):
        return bool(self._row)

class _PGCursor:
    """Compatibility cursor for the app's existing SQLite-style SQL."""
    def __init__(self, cursor):
        self._cursor = cursor
        self._lastrowid = None

    @staticmethod
    def _sql(sql):
        # Convert SQLite qmark placeholders at the DB boundary.
        return sql.replace("?", "%s")

    def execute(self, sql, params=None):
    sql2 = self._sql(sql)
    upper = sql2.lstrip().upper()

    # Preserve the existing two c.lastrowid call sites.
    if upper.startswith("INSERT INTO") and " RETURNING " not in upper:
        sql2 = sql2.rstrip().rstrip(";") + " RETURNING id"

    result = self._cursor.execute(sql2, params)

    if upper.startswith("INSERT INTO"):
        row = self._cursor.fetchone()

        if row:
            if isinstance(row, dict):
                self._lastrowid = next(iter(row.values()))
            else:
                self._lastrowid = row[0]
        else:
            self._lastrowid = None

    return result

    def executemany(self, sql, params_seq):
        return self._cursor.executemany(self._sql(sql), params_seq)

    def fetchone(self):
        row = self._cursor.fetchone()
        return None if row is None else _HybridRow(row)

    def fetchall(self):
        return [_HybridRow(row) for row in self._cursor.fetchall()]

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        return self._lastrowid

    def close(self):
        return self._cursor.close()

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class _PGConnection:
    """Compatibility wrapper around psycopg for the existing application."""
    def __init__(self, connection):
        self._connection = connection

    def cursor(self):
        return _PGCursor(self._connection.cursor())

    def execute(self, sql, params=None):
        return self.cursor().execute(sql, params)

    def commit(self):
        return self._connection.commit()

    def rollback(self):
        return self._connection.rollback()

    def close(self):
        return self._connection.close()

    @property
    def row_factory(self):
        return None

    @row_factory.setter
    def row_factory(self, value):
        # Existing SQLite code assigns sqlite3.Row. PostgreSQL rows are
        # converted to _HybridRow by _PGCursor instead.
        pass

    def __getattr__(self, name):
        return getattr(self._connection, name)


def _postgres_connection():
    return _PGConnection(
    psycopg.connect(DATABASE_URL, row_factory=dict_row)
)


def connect_for_setup(db_path=None):
    """Compatibility connection; schema is managed in PostgreSQL."""
    return _postgres_connection()


def get_db(db_path=None):
    """Get and cache the single PostgreSQL connection for this request."""
    if not hasattr(g, "db"):
        g.db = _postgres_connection()
    return g.db


@app.teardown_appcontext
def close_dbs(exception=None):
    """Close the PostgreSQL connection at request teardown."""
    conn = g.pop("db", None)
    if conn is not None:
        try:
            if exception is not None:
                conn.rollback()
            else:
                conn.commit()
        except Exception:
            logger.exception("Error finalizing PostgreSQL transaction")
            try:
                conn.rollback()
            except Exception:
                pass
        finally:
            conn.close()

# ======================================================
# Database setup
# ======================================================

def setup_databases():
    """
    PostgreSQL schema is managed separately by schema.sql.
    Do not create or migrate SQLite databases at application startup.
    """
    logger.info("PostgreSQL database ready; skipping SQLite setup.")


def create_admin_if_missing():
    """
    Create initial admin user from environment variables.
    If ADMIN_PASSWORD is not set, no seeded admin is created.
    """
    if not ADMIN_PASSWORD:
        logger.info("ADMIN_PASSWORD not provided: skipping auto-create admin")
        return

    conn = _postgres_connection()
    c = conn.cursor()

    try:
        c.execute("SELECT id FROM users WHERE username = ?", (ADMIN_USER,))
        if c.fetchone():
            return

        pw_hash = generate_password_hash(ADMIN_PASSWORD)
        c.execute(
            "INSERT INTO users "
            "(username, email, password_hash, email_verified, is_admin, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ADMIN_USER, "", pw_hash, 1, 1, now())
        )
        conn.commit()
        logger.info("Admin user created: %s", ADMIN_USER)
    finally:
        conn.close()


setup_databases()
create_admin_if_missing()

# ======================================================
# Session / conversation helpers
# ======================================================
def create_empty_conversation():
    conn = connect_for_setup(CONV_DB)
    c = conn.cursor()

    user_id = session.get("user_id")
    if not user_id:
        conn.close()
        return None

    c.execute(
        "INSERT INTO conversations (user_id, title, history, created_at) VALUES (?, ?, ?, ?)",
        (user_id, "__current__", json.dumps([]), now())
    )

    conv_id = c.lastrowid
    conn.commit()
    conn.close()
    return conv_id

def get_history_by_conv_id(conv_id):
    if not conv_id:
        return []
    conn = get_db(CONV_DB)
    if not conn:
        return []
    c = conn.cursor()
    c.execute(
    "SELECT history FROM conversations WHERE id = ? AND user_id = ?",
    (conv_id, session.get("user_id"))
)
    row = c.fetchone()
    return json.loads(row["history"]) if row and row["history"] else []

def save_history_by_conv_id(conv_id, history):
    if not conv_id:
        return
    conn = get_db(CONV_DB)
    if not conn:
        return
    c = conn.cursor()
    c.execute(
    "UPDATE conversations SET history = ?, created_at = ? WHERE id = ? AND user_id = ?",
    (json.dumps(history), now(), conv_id, session.get("user_id"))
)
    conn.commit()

def delete_conversation(conv_id):
    if not conv_id or not session.get("user_id"):
        return
    conn = get_db(CONV_DB)
    if not conn:
        return
    c = conn.cursor()
    c.execute(
        "DELETE FROM conversations WHERE id = ? AND user_id = ?",
        (conv_id, session.get("user_id"))
    )
    conn.commit()

# ======================================================
# Memory helpers (short summaries)
# ======================================================
def get_memory(conv_id):
    try:
        conn = get_db(CONV_DB)
        if not conn:
            return ""
        c = conn.cursor()
        c.execute(
            "SELECT summary FROM memories WHERE conv_id = ? "
            "ORDER BY updated_at DESC LIMIT 1",
            (conv_id,)
        )
        row = c.fetchone()
        return row["summary"] if row and row["summary"] else ""
    except Exception:
        logger.exception("Failed to load memory")
        return ""

def upsert_memory(conv_id, summary_text):
    if not summary_text:
        return
    try:
        conn = get_db(CONV_DB)
        if not conn:
            return
        c = conn.cursor()
        c.execute(
            "INSERT INTO memories (conv_id, summary, updated_at) VALUES (?, ?, ?)",
            (conv_id, summary_text, now())
        )
        conn.commit()
    except Exception:
        logger.exception("Failed to upsert memory")

def list_memories(conv_id):
    try:
        conn = get_db(CONV_DB)
        if not conn:
            return []
        c = conn.cursor()
        c.execute(
            "SELECT id, summary FROM memories WHERE conv_id = ? "
            "ORDER BY updated_at DESC",
            (conv_id,)
        )
        return [r["summary"] for r in c.fetchall()]
    except Exception:
        logger.exception("Failed to list memories")
        return []

def should_update_memory(chat_history, threshold_msgs=6):
    """
    Decide when to store a new memory summary.
    """
    user_msgs = [m for m in chat_history if m.get("role") == "user"]
    return len(user_msgs) >= threshold_msgs

# ======================================================
# Authentication helpers (new)
# ======================================================
def generate_otp():
    return str(random.randint(100000, 999999))

def login_user(user_row):
    session["user_id"] = user_row["id"]
    session["username"] = user_row["username"]
    session["is_admin"] = bool(user_row["is_admin"])
    session.permanent = True

    # 🔹 Update last_login timestamp
    conn = get_db(USER_DB)
    if conn:
        conn.execute(
            "UPDATE users SET last_login = ? WHERE id = ?",
            (now(), user_row["id"])
        )
        conn.commit()

def logout_user():
    for k in ("user_id", "username", "is_admin"):
        session.pop(k, None)

def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    conn = get_db(USER_DB)
    if not conn:
        return None
    c = conn.cursor()
    c.execute("""
    SELECT id, username, email, display_name,
           is_admin, created_at
    FROM users
    WHERE id = ?
""", (uid,))
    row = c.fetchone()
    return row

def get_display_name(user):
    """
    Returns a user-friendly name for UI display.
    Never expose raw 'admin' or system usernames to users.
    """
    if not user:
        return "There"

    username = user.get("username") if isinstance(user, dict) else user["username"]

    if not username or username.lower() == "admin":
        return "There"

    return username.capitalize()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({
                    "error": "auth_required",
                    "redirect": url_for("user_login")
                }), 401

            return redirect(url_for("user_login", next=request.path))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id") or not session.get("is_admin"):
            flash("Admin access required", "warning")
            return redirect(url_for("admin_login", next=request.path))
        return f(*args, **kwargs)
    return decorated

# ======================================================
# Safety / heuristics / moderation (original)
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
        "That message looks a bit like a test or typo. No problem — I’m right here when you’re ready. "
        "You can tell me what’s on your mind, or say 'help' to see some options. 💙"
    )

def safe_trim(text: str, max_len: int = 2000) -> str:
    text = (text or "").strip()
    if len(text) > max_len:
        text = text[:max_len]
    return text

def basic_empathy_reply(message, chat_history=None):
    """
    Heuristic layer to keep the tone warm and avoid repeating
    the same opener. Adapts based on how deep we are into the chat.
    (No exercises are suggested here; this is pure empathic response.)
    """
    msg = (message or "").lower()
    user_msgs = [m for m in (chat_history or []) if m.get("role") == "user"]
    depth = len(user_msgs)
    first_turn = depth <= 1

    def choose(first_line, follow_line):
        return first_line if first_turn else follow_line

    # Friendly greeting handling – always light and welcoming
    if any(word in msg for word in ["hi", "hii", "hey", "hello", "hola", "namaste", "namaskar"]):
        return "Hey, I’m glad you reached out. How are you feeling right now?"

    if any(word in msg for word in ["sad", "upset", "down", "depressed", "low"]):
        return choose(
            "I’m really sorry you’re feeling this way. You’re not alone — I’m right here with you. If you’d like, you can tell me a bit about what’s been weighing on you.",
            "It sounds like things are still feeling heavy. I’m still here with you — what’s feeling most tough for you right now?"
        )
    if any(word in msg for word in ["happy", "excited", "great", "good", "better"]):
        return choose(
            "That’s wonderful to hear. What’s been going well for you?",
            "I’m glad to hear some light in your day. What part of this feels most meaningful to you?"
        )
    if any(word in msg for word in ["anxious", "panic", "panicky", "nervous", "overwhelmed"]):
        return choose(
            "It’s okay to feel overwhelmed. If you’d like, you can describe what’s making you anxious and we can gently unpack it together.",
            "It still sounds quite intense. I’m here — what’s the part of this anxiety that shows up the strongest right now?"
        )
    if any(word in msg for word in ["angry", "mad", "furious", "rage"]):
        return choose(
            "I hear you — anger is a valid emotion. If you want to share what triggered it, we can look at it together.",
            "That anger sounds like it’s still there. What do you notice in your body or thoughts when it shows up?"
        )
    if any(word in msg for word in ["lonely", "alone", "isolated"]):
        return choose(
            "Feeling lonely can be really painful. You’re not actually alone here — I’m with you. Would you like to share what’s been happening around you lately?",
            "I hear that loneliness, and I’m still right here with you. What moments feel the loneliest for you these days?"
        )
    return None

# Stronger crisis detection with scoring
_CRISIS_PATTERNS = [
    (r"\bkill myself\b", 5),
    (r"\bwant to die\b", 5),
    (r"\bsuicid(e|al)\b", 5),
    (r"\bhurt myself\b", 4),
    (r"\bend my life\b", 5),
    (r"\bi can't go on\b", 4),
    (r"\bno reason to live\b", 4),
    (r"\bi'm going to kill myself\b", 6),
    (r"\bi might self[- ]harm\b", 4),
    (r"\bcut myself\b", 4),
]
_CRISIS_RE = [(re.compile(pat, re.IGNORECASE), score) for pat, score in _CRISIS_PATTERNS]

def compute_crisis_score(text: str) -> int:
    t = (text or "").strip()
    score = 0
    for patt, s in _CRISIS_RE:
        if patt.search(t):
            score += s
    if re.search(r"\bhopeless\b|\bworthless\b|\bcan't\b|\bcant\b", t, re.IGNORECASE):
        score += 1
    return score

# Crisis resources (basic)
CRISIS_RESOURCES = {
    "US": [
        {
            "label": "988 Suicide & Crisis Lifeline (US)",
            "phone": "988",
            "url": "https://988lifeline.org/",
        },
    ],
    "UK": [
        {
            "label": "Samaritans (UK)",
            "phone": "116 123",
            "url": "https://www.samaritans.org/",
        },
    ],
    "IN": [
        {
            "label": "AASRA (India)",
            "phone": "+91-9820466726",
            "url": "http://www.aasra.info/",
        },
    ],
    "AU": [
        {
            "label": "Lifeline Australia",
            "phone": "13 11 14",
            "url": "https://www.lifeline.org.au/",
        },
    ],
    "CA": [
        {
            "label": "Canada Suicide Prevention Service",
            "phone": "1.833.456.4566",
            "url": "https://www.crisisservicescanada.ca/",
        },
    ],
    "GLOBAL": [
        {
            "label": "International Suicide Hotlines",
            "phone": None,
            "url": "https://www.opencounseling.com/suicide-hotlines",
        },
        {
            "label": "Befrienders Worldwide",
            "phone": None,
            "url": "https://www.befrienders.org/",
        },
    ],
}

def get_country_from_request():
    country = None
    if request.headers.get("X-User-Country"):
        country = request.headers.get("X-User-Country")
    elif request.headers.get("CF-IPCountry"):
        country = request.headers.get("CF-IPCountry")
    else:
        al = request.headers.get("Accept-Language", "")
        if al:
            code = al.split(",")[0].strip()
            if "-" in code:
                country = code.split("-")[-1].upper()
            else:
                lang = code.split("-")[0].lower()
                if lang == "en":
                    country = "US"
                elif lang == "hi":
                    country = "IN"
    if country:
        country = country.upper()
    return country

def get_crisis_resources(country_code=None):
    country_code = country_code or get_country_from_request()
    if country_code and country_code in CRISIS_RESOURCES:
        return CRISIS_RESOURCES[country_code]
    return CRISIS_RESOURCES["GLOBAL"]

# Simple moderation (regex-based)
_DISALLOWED_RE = re.compile(
    r"\b(bomb|kill someone|terror|rape|explosives|child sexual)\b",
    re.IGNORECASE,
)

def moderate_text(text: str):
    if not text:
        return True, None
    if _DISALLOWED_RE.search(text):
        return False, "disallowed_content"
    return True, None

# ======================================================
# Breathlessness / shortness-of-breath detection
# ======================================================
_BREATHLESS_PATTERNS = [
    r"\bcan't breathe\b",
    r"\bcant breathe\b",
    r"\bnot breathing\b",
    r"\bim breathless\b",
    r"\bi'm breathless\b",
    r"\bbreathless\b",
    r"\bshort of breath\b",
    r"\bshortness of breath\b",
    r"\bhyperventilat",
    r"\bpanic attack\b",
    r"\bpanic\b",
    r"\bim panicking\b",
    r"\bi'm panicking\b",
]
_BREATHLESS_RE = [re.compile(p, re.IGNORECASE) for p in _BREATHLESS_PATTERNS]

def matches_breathless(text: str) -> bool:
    t = (text or "").strip()
    for patt in _BREATHLESS_RE:
        if patt.search(t):
            return True
    return False

def handle_breathless_inline(user_text: str):
    """
    Returns (reply_text, action) for breathlessness/panic where action is None
    or a structured dict. Provides inline grounding/breathing steps.
    """
    try:
        logger.info("BREATHLESS_DETECTED snippet=%s", user_text[:200])
    except Exception:
        pass

    reply_lines = [
        "That sounds really frightening, and I’m glad you told me. Let’s slow things down gently together for a moment.",
        "If you can, sit comfortably and place one hand on your belly and one on your chest.",
        "Breathe in softly through your nose for 4 seconds and feel your belly rise, hold for 2 seconds, then breathe out slowly through your mouth for 6 seconds.",
        "Try this for 3 rounds and just notice any tiny shift, even if it’s small.",
        "If you’d like, I can guide you through a short timed breathing exercise here, or we can try other grounding techniques. Reply 'guide' for breathing, or 'ground' if you want different grounding ideas.",
    ]
    return (
        " ".join(reply_lines),
        {"type": "inline_breathing", "severity_hint": "panic/breathless"},
    )

# ======================================================
# Simple TF-based "embedding" prototype + similarity
# ======================================================
_WORD_RE = re.compile(r"\b[a-zA-Z']{2,}\b")

def tokenize(text):
    text = (text or "").lower()
    return _WORD_RE.findall(text)

def build_tf_vector(text):
    tokens = tokenize(text)
    vec = {}
    for t in tokens:
        vec[t] = vec.get(t, 0) + 1
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    for k in list(vec.keys()):
        vec[k] = vec[k] / norm
    return vec

def cosine_sim(vec_a, vec_b):
    if not vec_a or not vec_b:
        return 0.0
    if len(vec_a) > len(vec_b):
        vec_a, vec_b = vec_b, vec_a
    s = 0.0
    for k, v in vec_a.items():
        if k in vec_b:
            s += v * vec_b[k]
    return s

def retrieve_relevant_memories(conv_id, query, top_k=3):
    try:
        memories = list_memories(conv_id)
        if not memories:
            return []
        q_vec = build_tf_vector(query)
        scored = []
        for m in memories:
            m_vec = build_tf_vector(m)
            score = cosine_sim(q_vec, m_vec)
            scored.append((score, m))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for s, m in scored[:top_k] if s > 0.0]
    except Exception:
        logger.exception("Memory retrieval failed")
        return []

# ======================================================
# Simple language hint (English vs Hindi) for prompt
# ======================================================
def detect_language_hint_for_prompt(text: str) -> str:
    """
    Very lightweight detection:
    - If the text contains Devanagari characters -> 'hi'
    - Otherwise -> 'en'
    Used only to hint the model which language to respond in.
    """
    t = text or ""
    for ch in t:
        code = ord(ch)
        if 0x0900 <= code <= 0x097F:  # Devanagari range (Hindi and related)
            return "hi"
    return "en"

# ======================================================
# Redirect intent detection & summarization helpers
# ======================================================
def detect_redirect_intent(user_text):
    """
    Only return a redirect when user explicitly expresses intent
    to open/start/show a breathing exercise or journal page.
    """
    t = (user_text or "").strip().lower()
    if re.search(
        r"\b(open|go to|show|start|begin|take me to|launch)\b.*\b(breath|breathing|breathing exercise|guided breathing)\b",
        t,
    ):
        return {"type": "redirect", "url": "/breathing", "label": "breathing"}
    if re.search(
        r"\b(open|go to|show|start|begin|take me to|launch)\b.*\b(journal|journaling|journal entry)\b",
        t,
    ):
        return {"type": "redirect", "url": "/journaling", "label": "journal"}
    if re.search(
        r"\b(start breathing exercise|guided breathing|breathing exercise|guide me through breathing)\b",
        t,
    ):
        return {"type": "redirect", "url": "/breathing", "label": "breathing"}
    if re.search(
        r"\b(open journal|open journaling|start journaling|write in my journal)\b",
        t,
    ):
        return {"type": "redirect", "url": "/journaling", "label": "journal"}
    return None

def summarize_history_for_memory(chat_history):
    try:
        snippet = "\n".join(
            [
                f"User: {m['content']}" if m["role"] == "user" else f"Assistant: {m['content']}"
                for m in chat_history[-30:]
            ]
        )
        system = {
            "role": "system",
            "content": (
                "Summarize the user's key facts, patterns, and concerns from this conversation "
                "in 2 short factual sentences for memory storage. "
                "Focus on stable themes rather than moment-to-moment details."
            ),
        }
        messages = [system, {"role": "user", "content": safe_trim(snippet, 4000)}]
        summary = call_openrouter_with_retries(messages, retries=1, timeout=8)
        return safe_trim(summary, max_len=800)
    except Exception:
        logger.exception("Memory summarization failed")
        return ""

# ======================================================
# OpenRouter integration (safer)
# ======================================================
def prepare_messages(chat_history, limit=16, per_msg_max=1200):
    """
    Convert internal history format to OpenAI-style messages.
    We keep a reasonable window (default 16 turns) for continuity.
    """
    msgs = [m for m in chat_history if m.get("role") in ("user", "model")]
    msgs = msgs[-limit:]
    out = []
    for m in msgs:
        role = "assistant" if m["role"] == "model" else m["role"]
        out.append({"role": role, "content": safe_trim(m["content"], max_len=per_msg_max)})
    return out

def call_openrouter_with_retries(messages, retries=2, timeout=10):
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not configured")
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "gpt-4o-mini",
    "messages": messages,

    # 🧠 Response behavior tuning
    "temperature": 0.65,        # calmer, more thoughtful
    "top_p": 0.9,

    # 🔁 Reduce repetition & looping
    "presence_penalty": 0.3,    # encourages new ideas gently
    }

    last_exc = None
    for attempt in range(retries + 1):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
            resp.raise_for_status()
            result = resp.json()
            if "choices" in result and result["choices"]:
                text = result["choices"][0]["message"]["content"]
                return remove_ai_language(text) or graceful_gibberish_reply()
            logger.warning("OpenRouter returned unexpected shape: %s", result)
            break
        except Exception as e:
            last_exc = e
            logger.exception("OpenRouter call failed (attempt %s): %s", attempt + 1, e)
            time.sleep(0.5 * (attempt + 1))
    raise last_exc or RuntimeError("OpenRouter unknown error")

def remove_ai_language(reply):
    blacklist = [
        "as an AI",
        "as an assistant",
        "as a chatbot",
        "i'm just a bot",
        "i'm not human",
        "i am a virtual assistant",
        "as a language model",
        "I don't have emotions",
        "I'm not a human",
    ]
    out = reply or ""
    for phrase in blacklist:
        out = out.replace(phrase, "")
    return out.strip()

# ======================================================
# Core: generate_reply_with_context -> (reply_text, action)
# ======================================================
def generate_reply_with_context(chat_history, conv_id=None, allow_remote_processing=False):
    """
    FINAL production-grade chat brain for Theramind.
    AI-first, continuity-aware, emotionally intelligent, safety-aligned.
    """

    # -------------------------------------------------
    # Extract last user message
    # -------------------------------------------------
    last_user_message = next(
        (m["content"] for m in reversed(chat_history) if m.get("role") == "user"),
        "",
    )
    last_user_message = safe_trim(last_user_message, 2000)

    # -------------------------------------------------
    # Hard moderation (only truly disallowed content)
    # -------------------------------------------------
    allowed, _ = moderate_text(last_user_message)
    if not allowed:
        return "I’m sorry — I can’t help with that request.", None

    # -------------------------------------------------
    # Crisis detection (HIGH PRIORITY)
    # -------------------------------------------------
    crisis_score = compute_crisis_score(last_user_message)
    if crisis_score >= 4:
        resources = get_crisis_resources()
        lines = [
            "I’m really glad you told me this. What you’re describing sounds overwhelming, and your safety matters deeply.",
            "If you feel like you might hurt yourself or are in immediate danger, please contact your local emergency services right now.",
        ]
        for r in resources:
            if r.get("phone"):
                lines.append(f"{r['label']}: {r['phone']} ({r.get('url','')})")
            else:
                lines.append(f"{r['label']}: {r.get('url')}")
        lines.append(
            "If you’re able, we can also stay here together and talk through what you’re feeling."
        )
        return "\n".join(lines), {
            "type": "crisis",
            "resources": resources,
            "score": crisis_score,
        }

    # -------------------------------------------------
    # Panic / breathlessness handling
    # -------------------------------------------------
    if matches_breathless(last_user_message):
        return handle_breathless_inline(last_user_message)

    # -------------------------------------------------
    # Gibberish / accidental input
    # -------------------------------------------------
    if looks_like_gibberish(last_user_message):
        return graceful_gibberish_reply(), None

    # -------------------------------------------------
    # Detect explicit redirect intent (journal / breathing)
    # -------------------------------------------------
    redirect_intent = detect_redirect_intent(last_user_message)
    if redirect_intent:
        return (
            f"Alright — taking you to the {redirect_intent['label']} now.",
            redirect_intent
    )


    # -------------------------------------------------
    # Prepare AI messages
    # -------------------------------------------------
    messages = []

    # Language detection (lightweight, non-invasive)
    recent_user_text = " ".join(
        [m["content"] for m in chat_history if m.get("role") == "user"][-3:]
    )
    lang_code = detect_language_hint_for_prompt(recent_user_text)

    if lang_code == "hi":
        lang_instruction = (
            "Respond in natural, conversational Hindi. "
            "If the user mixes Hindi and English, respond in natural Hinglish."
        )
    else:
        lang_instruction = (
            "Respond in natural, conversational English. "
            "If the user mixes languages, mirror their style naturally."
        )


    # Persona & style: friend + therapist vibe, continuity-aware, multilingual
    system_prompt = {
    "role": "system",
    "content": (
        "You are **Theramind**, a world-class mental wellness companion designed for global users. "
        "You are calm, emotionally intelligent, deeply attentive, and grounded. You speak like a thoughtful human — "
        "never robotic, scripted, preachy, or repetitive.\n\n"

        "=== CORE IDENTITY ===\n"
        "- You are NOT a doctor, but you are highly informed about mental health, wellbeing, stress, anxiety, and emotional regulation.\n"
        "- You may provide **safe, general medical and mental health guidance**, lifestyle suggestions, and evidence-based practices, "
        "but you must NEVER diagnose conditions, prescribe medications, or claim clinical authority.\n"
        "- When something may require professional or emergency help, you gently and clearly encourage seeking it.\n\n"

        "=== LANGUAGE & CULTURE ===\n"
        f"- {lang_instruction}\n"
        "- Match the user's language naturally (English, Hindi, or mixed Hinglish if the user mixes).\n"
        "- Use culturally neutral, globally understandable language.\n\n"

        "=== CONVERSATION INTELLIGENCE (VERY IMPORTANT) ===\n"
        "- Maintain **strong continuity** across the conversation.\n"
        "- Remember what the user has already shared and build on it.\n"
        "- NEVER repeat the same opening lines, advice, or questions unnecessarily.\n"
        "- Do NOT ask generic questions like 'Can you tell me more?' repeatedly.\n"
        "- If the user has already tried something (e.g., breathing, grounding), acknowledge it and adapt — do NOT restart it blindly.\n\n"

        "=== RESPONSE STYLE ===\n"
        "- Validate emotions clearly and specifically.\n"
        "- Be concise but meaningful (typically 2–6 sentences).\n"
        "- Prefer thoughtful reflections and gentle insights over long explanations.\n"
        "- Ask open-ended questions only when they truly move the conversation forward.\n"
        "- Avoid clichés, therapy-speak, or motivational fluff.\n\n"

        "=== MEDICAL & WELLNESS GUIDANCE ===\n"
        "- You MAY suggest:\n"
        "  • grounding techniques\n"
        "  • breathing practices\n"
        "  • sleep hygiene tips\n"
        "  • nutrition & hydration awareness\n"
        "  • exercise, sunlight, routines\n"
        "  • when to consider talking to a professional\n"
        "- You MUST phrase medical-related advice as:\n"
        "  'Many people find...', 'In general, it can help to...', 'You might consider...'\n"
        "- NEVER say or imply you are a medical professional.\n\n"

        "=== SAFETY ===\n"
        "- If the user expresses self-harm, suicidal thoughts, or medical emergencies, prioritize safety and crisis guidance immediately.\n"
        "- Be calm, direct, and supportive — never alarmist or dismissive.\n\n"

        "=== OVERALL GOAL ===\n"
        "Your goal is to help the user feel:\n"
        "- understood\n"
        "- emotionally safer\n"
        "- mentally clearer\n"
        "- supported without dependence\n\n"

        "Respond as a thoughtful human companion who genuinely remembers and cares."
        "- If your response would repeat phrasing from your last 2 messages, rephrase it completely."

    ),
}
       # -------------------------------------------------
    # Retrieve high-level memories (previous summaries)
    # -------------------------------------------------

    memories = []

    if conv_id and allow_remote_processing:
        memories = retrieve_relevant_memories(
            conv_id,
            last_user_message,
            top_k=3
        )

    if memories:
        messages.append(
            {
                "role": "system",
                "content": (
                    "Relevant long-term context about this user:\n"
                    + " | ".join([safe_trim(m, 300) for m in memories])
                    + "\nUse this only for continuity. Do NOT repeat it verbatim."
                ),
            }
        )

    # Always add system prompt AFTER memory context
    messages.append(system_prompt)

    # -------------------------------------------------
    # Conversation history
    # -------------------------------------------------
    if allow_remote_processing:
        messages.extend(prepare_messages(chat_history, limit=18, per_msg_max=1200))
    else:
        recap = []
        for m in chat_history[-6:]:
            role = "User" if m["role"] == "user" else "Theramind"
            recap.append(f"{role}: {safe_trim(m['content'], 200)}")
        messages.append(
            {
                "role": "user",
                "content": (
                    "Conversation recap:\n"
                    + "\n".join(recap)
                    + "\n\nUser now says:\n"
                    + last_user_message
                ),
            }
        )

    # -------------------------------------------------
    # AI GENERATION
    # -------------------------------------------------
    try:
        reply_text = call_openrouter_with_retries(
            messages, retries=2, timeout=12
        )
    except Exception:
        reply_text = random.choice(
            [
                "I’m here with you. We can take this one step at a time.",
                "Thanks for trusting me with this. What feels most important right now?",
                "I’m still with you. We don’t have to rush this.",
            ]
        )

    reply_text = remove_ai_language(reply_text).strip()

    # -------------------------------------------------
    # Memory update (summarize only when meaningful)
    # -------------------------------------------------
    try:
        if (
            conv_id
            and allow_remote_processing
            and should_update_memory(chat_history, threshold_msgs=6)
        ):
            summary = summarize_history_for_memory(chat_history)
            if summary:
                upsert_memory(conv_id, summary)
    except Exception:
        logger.exception("Memory update failed")

    return reply_text, None

# ======================================================
# Routes & session handling (original + admin additions)
# ======================================================
# =========================
# User Authentication Routes
# =========================
@app.route("/login", methods=["GET", "POST"])
@csrf.exempt
@limiter.limit("50 per hour")
def user_login():
    if request.method == "POST":
        email_or_username = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        conn = get_db(USER_DB)
        c = conn.cursor()

        c.execute("""
            SELECT * FROM users
            WHERE email = ? OR username = ?
        """, (email_or_username, email_or_username))

        user = c.fetchone()

        if not user or not check_password_hash(user["password_hash"], password):
            flash("Invalid email or password.", "danger")
            return redirect(url_for("user_login"))

        if not user["email_verified"]:
            session["pending_otp_email"] = user["email"]
            flash("Please verify your email first.", "warning")
            return redirect(url_for("verify_signup_otp"))

        login_user(user)
        flash(f"Welcome back, {user['username']} 👋", "success")
        return redirect(url_for("home"))

    return render_template("auth/login.html")



from secrets import token_urlsafe

@app.route("/auth/google")
def auth_google():
    nonce = token_urlsafe(16)
    session["google_nonce"] = nonce

    redirect_uri = "https://theramind.onrender.com/auth/google/callback"

    return oauth.google.authorize_redirect(
        redirect_uri=redirect_uri,
        nonce=nonce
    )



@app.route("/auth/google/callback")
@csrf.exempt
def auth_google_callback():
    session.modified = True

    try:
        token = oauth.google.authorize_access_token()

        user_info = token.get("userinfo")
        if not user_info:
            raise Exception("No userinfo returned by Google")

    except Exception as e:
        logout_user()
        session.pop("google_nonce", None)
        session.pop("oauth_temp_user", None)

        print("Google OAuth error:", e)
        flash("Google authentication failed. Please try again.", "danger")
        return redirect(url_for("user_login"))

    email = user_info.get("email")
    name = user_info.get("name") or email.split("@")[0]

    conn = get_db(USER_DB)
    c = conn.cursor()

    c.execute("SELECT * FROM users WHERE email = ?", (email,))
    user = c.fetchone()

    if user:
        login_user(user)
        flash(f"✨ Welcome back, {user['username']}.", "success")
        return redirect(url_for("home"))

    session["oauth_temp_user"] = {
        "username": name,
        "email": email
    }

    return redirect(url_for("oauth_confirm"))




@app.route("/auth/confirm", methods=["GET"])
@csrf.exempt
def oauth_confirm():
    temp = session.get("oauth_temp_user")

    if not temp:
        flash("Authentication session expired. Please try again.", "danger")
        return redirect(url_for("user_login"))

    conn = get_db(USER_DB)
    c = conn.cursor()

    #  Check if user already exists
    c.execute("SELECT * FROM users WHERE email = ?", (temp["email"],))
    existing = c.fetchone()

    if existing:
        # Existing user → log in
        login_user(existing)
        session.pop("oauth_temp_user", None)
        flash("Welcome back ✨", "success")
        return redirect(url_for("home"))

    #  New Google user → create account
    pw_hash = generate_password_hash(os.urandom(16).hex())

    c.execute(
        """
        INSERT INTO users (
            username,
            email,
            password_hash,
            auth_provider,
            email_verified,
            created_at
        )
        VALUES (?, ?, ?, 'google', 1, ?)
        """,
        (
            temp["username"],
            temp["email"],
            pw_hash,
            now()
        )
    )
    conn.commit()

    # Log in newly created user
    c.execute("SELECT * FROM users WHERE email = ?", (temp["email"],))
    user = c.fetchone()
    login_user(user)

    session.pop("oauth_temp_user", None)
    flash("Your account has been created successfully ✨", "success")
    return redirect(url_for("home"))




@app.route("/auth/verify-otp", methods=["GET", "POST"])
@csrf.exempt
def verify_signup_otp():
    email = session.get("pending_otp_email")

    if not email:
        flash("Signup session expired. Please sign up again.", "danger")
        return redirect(url_for("signup"))

    if request.method == "GET":
        return render_template("auth/verify_otp.html")

    otp = request.form.get("otp", "").strip()

    if not otp.isdigit() or len(otp) != 6:
        flash("Please enter a valid 6-digit code.", "danger")
        return redirect(url_for("verify_signup_otp"))

    conn = get_db(USER_DB)
    c = conn.cursor()

    c.execute(
        """
        SELECT otp, expires_at
        FROM email_otps
        WHERE email = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (email,)
    )
    row = c.fetchone()

    if not row or row["otp"] != otp or row["expires_at"] < int(time.time()):
        flash("Invalid or expired verification code.", "danger")
        return redirect(url_for("verify_signup_otp"))

    # Verify user
    c.execute(
        "UPDATE users SET email_verified = 1 WHERE email = ?",
        (email,)
    )
    c.execute("DELETE FROM email_otps WHERE email = ?", (email,))
    conn.commit()

    c.execute("SELECT * FROM users WHERE email = ?", (email,))
    user = c.fetchone()
    login_user(user)

    session.pop("pending_otp_email", None)

    flash("🌱 Your account is verified. Welcome to Theramind.", "success")
    return redirect(url_for("home"))




@app.route("/signup", methods=["GET", "POST"])
@csrf.exempt
@limiter.limit("20 per hour")
def signup():
    if request.method == "POST":
        display_name = request.form.get("display_name", "").strip()
        intent = request.form.get("intent", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password or not intent:
            flash("Please complete all required fields.", "danger")
            return redirect(url_for("signup"))

        if len(password) < 8:
            flash("Password must be at least 8 characters.", "danger")
            return redirect(url_for("signup"))

        conn = get_db(USER_DB)
        c = conn.cursor()

        c.execute("SELECT id, email_verified FROM users WHERE email = ?", (email,))
        existing = c.fetchone()

        # Already verified → go to login
        if existing and existing["email_verified"] == 1:
            flash("Account already exists. Please sign in.", "warning")
            return redirect(url_for("user_login"))

        # Create user if new
        if not existing:
            pw_hash = generate_password_hash(password)
            c.execute("""
                INSERT INTO users (
                    username, email, password_hash,
                    display_name, intent, auth_provider,
                    email_verified, created_at
                )
                VALUES (?, ?, ?, ?, ?, 'email', 0, ?)
            """, (
                display_name or email.split("@")[0],
                email,
                pw_hash,
                display_name,
                intent,
                now()
            ))
            conn.commit()

        # Generate OTP
        otp = generate_otp()
        expires_at = int(time.time()) + 600

        c.execute("DELETE FROM email_otps WHERE email = ?", (email,))
        c.execute(
            "INSERT INTO email_otps (email, otp, expires_at) VALUES (?, ?, ?)",
            (email, otp, expires_at)
        )
        conn.commit()

        # Send OTP safely
        try:
            send_otp_email(email, otp)
        except Exception as e:
            logger.exception("OTP email failed")
            c.execute("DELETE FROM email_otps WHERE email = ?", (email,))
            conn.commit()
            
            flash("Email service is temporarily unavailable. Please try again.", "danger")
            return redirect(url_for("signup"))

        # 🔑 DO NOT CLEAR ENTIRE SESSION
        session.pop("pending_otp_email", None)
        session["pending_otp_email"] = email

        flash("We’ve sent a verification code to your email.", "success")
        return redirect(url_for("verify_signup_otp"))

    return render_template("auth/signup.html")



@app.route("/logout")
def user_logout():

    # Clear conversation session too
    session.pop("conv_id", None)

    logout_user()

    flash("You have been logged out successfully.", "success")

    return redirect(url_for("home"))


@app.route("/dashboard")
@login_required
def user_dashboard():
    return render_template("dashboard.html", user=current_user())

@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = current_user()
    if not user:
        flash("Your session expired. Please log in again.", "warning")
        return redirect(url_for("user_login"))

    display_name = get_display_name(user)

    conn_users = get_db(USER_DB)

    conn_conv = get_db(CONV_DB)

    conn_journal = get_db(JOURNAL_DB)

    conn_mood = get_db(MOOD_DB)

    # ---------- PASSWORD UPDATE ----------
    if request.method == "POST" and "current_password" in request.form:
        current_pw = request.form.get("current_password", "")
        new_pw = request.form.get("new_password", "")

        row = conn_users.execute(
            "SELECT password_hash FROM users WHERE id = ?",
            (user["id"],)
        ).fetchone()

        if not row or not check_password_hash(row["password_hash"], current_pw):
            flash("Current password is incorrect.", "danger")
            return redirect(url_for("profile"))

        if len(new_pw) < 8:
            flash("Password must be at least 8 characters.", "danger")
            return redirect(url_for("profile"))

        conn_users.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (generate_password_hash(new_pw), user["id"])
        )
        conn_users.commit()

        flash("Password updated successfully 🔐", "success")
        return redirect(url_for("profile"))

    # ---------- GOALS UPDATE ----------
    if request.method == "POST" and "goals" in request.form:
        goals = request.form.get("goals", "").strip()

        conn_users.execute(
            """
            INSERT INTO user_profile (user_id, goals)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET goals = excluded.goals
            """,
            (user["id"], goals)
        )
        conn_users.commit()

        flash("Your intentions have been saved 🌱", "success")
        return redirect(url_for("profile"))

    # ---------- STATS ----------
    conversations = conn_conv.execute(
        "SELECT COUNT(*) c FROM conversations WHERE user_id = ? AND title != '__current__'",
        (user["id"],)
    ).fetchone()["c"]

    journals = conn_journal.execute(
        "SELECT COUNT(*) c FROM journal_entries WHERE user_id = ?",
        (user["id"],)
    ).fetchone()["c"]

    moods = conn_mood.execute(
        "SELECT COUNT(*) c FROM mood_logs WHERE user_id = ?",
        (user["id"],)
    ).fetchone()["c"]

    last_mood = conn_mood.execute(
        "SELECT mood, date FROM mood_logs WHERE user_id = ? ORDER BY id DESC LIMIT 1",
        (user["id"],)
    ).fetchone()

    goals_row = conn_users.execute(
        "SELECT goals FROM user_profile WHERE user_id = ?",
        (user["id"],)
    ).fetchone()

    return render_template(
        "auth/profile.html",
        user=user,
        display_name=display_name,
        stats={
            "conversations": conversations,
            "journals": journals,
            "moods": moods
        },
        last_mood=last_mood,
        goals=goals_row["goals"] if goals_row else ""
    )
    
@app.route("/journaling", methods=["GET", "POST"])
@csrf.exempt
@login_required
def journaling():

    if request.method == "GET":
        return render_template("journaling.html")

    try:

        print("📥 POST /journaling received")

        title = request.form.get("title", "Untitled")
        content = request.form.get("content", "")
        mood = request.form.get("mood", "")
        tags = request.form.get("tags", "")

        if not content.strip():
            return jsonify({"ok": False})

        user_id = session.get("user_id")

        conn = _postgres_connection()

        conn.execute("""
            INSERT INTO journal_entries
            (user_id, title, content, mood, tags, date)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            title,
            content,
            mood,
            tags,
            now()
        ))

        conn.commit()
        conn.close()

        print("✅ Saved entry")

        return jsonify({"ok": True})

    except Exception as e:

        print("❌ SAVE ERROR:", e)

        return jsonify({"ok": False})
    
@app.route("/api/history/journals")
@csrf.exempt
@login_required
def get_journal_history():

    try:

        conn = _postgres_connection()

        rows = conn.execute("""
            SELECT id, date, title, content, mood, tags
            FROM journal_entries
            WHERE user_id = ?
            ORDER BY id DESC
        """, (session["user_id"],)).fetchall()

        conn.close()

        journals = []

        for row in rows:

            journals.append({
                "id": row["id"],
                "date": row["date"],
                "title": row["title"],
                "content": row["content"],
                "mood": row["mood"],
                "tags": row["tags"]
            })

        print("📘 Found entries:", len(journals))

        return jsonify(journals)

    except Exception as e:

        print("❌ HISTORY ERROR:", e)

        return jsonify([])

@app.route("/api/journals/<int:entry_id>", methods=["DELETE"])
@login_required
def delete_journal(entry_id):

    try:
        conn = get_db(JOURNAL_DB)

        conn.execute(
            """
            DELETE FROM journal_entries
            WHERE id = ?
            AND user_id = ?
            """,
            (
                entry_id,
                session["user_id"]
            )
        )

        conn.commit()

        print(f"🗑️ Deleted entry {entry_id}")

        return jsonify({"ok": True})

    except Exception as e:
        logger.exception(
            "Delete failed: %s",
            e
        )

        return jsonify({"ok": False}), 500
    
@app.before_request
def ensure_session_and_conv():
    """
    Ensure:
    - session is permanent
    - consent flag exists
    - chat throttling
    - conversation exists ONLY for logged-in users who need it
    """

    # -----------------------------
    # Always keep session permanent
    # -----------------------------
    
    if session.get("user_id"):
     session.permanent = True

    # ---------------------------------
    # Default consent (can be changed)
    # ---------------------------------
    if "allow_remote_processing" not in session:
        session["allow_remote_processing"] = True

    # ---------------------------------
    # Throttle chat requests only
    # ---------------------------------
    if request.endpoint == "chat" and request.method == "POST":
        now_time = time.time()
        last = session.get("last_request", 0)

        if now_time - last < 0.4:
            return jsonify({
                "reply": "I’m still finishing the last message. Just a moment, then you can send again. 💙",
                "action": None,
            })

        session["last_request"] = now_time

    # ----------------------------------------------------
    # Create conversation ONLY when user is logged in
    # and accessing chat-related pages
    # ----------------------------------------------------
    chat_related_endpoints = {
        "chat",
        "index",
        "get_current_session",
        "get_current_conversation",
        "reset_session",
    }

    if (
        session.get("user_id") and
        request.endpoint in chat_related_endpoints and
        "conv_id" not in session
    ):
        try:
             conv_id = create_empty_conversation()
             if conv_id:
                 session["conv_id"] = conv_id
        except Exception:
            logger.exception("Failed to create conversation for user_id=%s", session.get("user_id"))

@app.route("/admin/login", methods=["GET", "POST"])
@csrf.exempt
@limiter.limit("10 per minute")
def admin_login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        if not username or not password:
            flash("Please provide username and password", "danger")
            return redirect(url_for("admin_login"))

        conn = get_db(USER_DB)
        if not conn:
            flash("User database not available", "danger")
            return redirect(url_for("admin_login"))

        c = conn.cursor()
        c.execute(
            """
            SELECT id, username, password_hash, is_admin
            FROM users
            WHERE username = ?
            LIMIT 1
            """,
            (username,)
        )
        user = c.fetchone()

        # ❌ User not found
        if not user:
            flash("Invalid username or password", "danger")
            return redirect(url_for("admin_login"))

        # ❌ Password mismatch
        if not check_password_hash(user["password_hash"], password):
            flash("Invalid username or password", "danger")
            return redirect(url_for("admin_login"))

        # ❌ Not an admin
        if not user["is_admin"]:
            flash("Admin access required", "danger")
            return redirect(url_for("admin_login"))

        # ✅ SUCCESS
        login_user(user)
        logger.info("Admin logged in: %s", username)

        return redirect(request.args.get("next") or url_for("admin_dashboard"))

    return render_template("admin/login.html")


@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    # Just render; front-end will fetch data via API endpoints
    return render_template("admin/dashboard.html")

@app.route("/admin/users")
@admin_required
def admin_list_users():
    conn = get_db(USER_DB)
    if not conn:
        return jsonify([])

    c = conn.cursor()
    c.execute("""
        SELECT 
            id,
            username,
            email,
            email_verified,
            is_admin,
            created_at,
            last_login,
            display_name,
            intent,
            auth_provider
        FROM users
        ORDER BY created_at DESC
    """)

    rows = c.fetchall()

    return jsonify([
        {
            "id": r["id"],
            "username": r["username"],
            "email": r["email"],
            "email_verified": bool(r["email_verified"]),
            "is_admin": bool(r["is_admin"]),
            "created_at": r["created_at"],
            "last_login": r["last_login"],
            "display_name": r["display_name"],
            "intent": r["intent"],
            "login_type": (r["auth_provider"] or "email").capitalize()
        }
        for r in rows
    ])

@app.route("/admin/create_user", methods=["POST"])
@admin_required
def admin_create_user():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    is_admin = bool(data.get("is_admin", False))

    if not email or not password:
        return jsonify({"status": "failed", "message": "email & password required"}), 400

    pw_hash = generate_password_hash(password)
    conn = get_db(USER_DB)
    c = conn.cursor()

    try:
        # Email verified = 1 (admin-created users don’t need OTP)
        c.execute("""
            INSERT INTO users (
                username,
                email,
                password_hash,
                email_verified,
                is_admin,
                created_at
            )
            VALUES (?, ?, ?, 1, ?, ?)
        """, (
            username or email.split('@')[0],
            email,
            pw_hash,
            int(is_admin),
            now()
        ))

        new_user_id = c.lastrowid
       
        # Log admin action
        c.execute("""
            INSERT INTO admin_logs (admin_id, action, target_user_id, timestamp)
            VALUES (?, ?, ?, ?)
        """, (
            session.get("user_id"),
            "create_user",
            new_user_id,
            now()
        ))

        conn.commit()

        return jsonify({"status": "ok", "id": new_user_id})

    except psycopg_errors.UniqueViolation:
        return jsonify({"status": "failed", "message": "username or email already exists"}), 400

# ---------- Admin management API endpoints (attach near other /admin routes) ----------

@app.route("/admin/delete_user/<int:user_id>", methods=["DELETE"])
@admin_required
def admin_delete_user(user_id):
    """Delete a user by id (admin only). Protect from deleting currently logged-in admin."""
    cur_user = current_user()
    if cur_user and cur_user["id"] == user_id:
        return jsonify({"status": "failed", "message": "Cannot delete your own account"}), 400

    conn = get_db(USER_DB)
    if not conn:
        return jsonify({"status": "failed", "message": "User DB unavailable"}), 500

    c = conn.cursor()

    try:
        # 🔹 Delete user (CASCADE will handle related data if FK enabled)
        c.execute("DELETE FROM users WHERE id = ?", (user_id,))

        # 🔹 Log admin action
        c.execute("""
            INSERT INTO admin_logs (admin_id, action, target_user_id, timestamp)
            VALUES (?, ?, ?, ?)
        """, (
            session.get("user_id"),
            "delete_user",
            user_id,
            now()
        ))

        conn.commit()

        return jsonify({"status": "ok"})

    except Exception:
        logger.exception("Failed to delete user %s", user_id)
        return jsonify({"status": "failed", "message": "DB error"}), 500

@app.route("/admin/toggle_admin/<int:user_id>", methods=["POST"])
@admin_required
def admin_toggle_admin(user_id):
    """Promote or demote a user as admin. Returns the new is_admin value."""
    cur_user = current_user()
    if cur_user and cur_user["id"] == user_id:
        return jsonify({"status": "failed", "message": "Cannot change your own admin status"}), 400

    conn = get_db(USER_DB)
    if not conn:
        return jsonify({"status": "failed", "message": "User DB unavailable"}), 500

    c = conn.cursor()

    try:
        c.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,))
        row = c.fetchone()

        if not row:
            return jsonify({"status": "failed", "message": "User not found"}), 404

        new_val = 0 if row["is_admin"] else 1

        # 🔹 Update admin status
        c.execute("UPDATE users SET is_admin = ? WHERE id = ?", (int(new_val), user_id))

        # 🔹 Log admin action
        c.execute("""
            INSERT INTO admin_logs (admin_id, action, target_user_id, timestamp)
            VALUES (?, ?, ?, ?)
        """, (
            session.get("user_id"),
            "toggle_admin",
            user_id,
            now()
        ))

        conn.commit()

        return jsonify({"status": "ok", "is_admin": bool(new_val)})

    except Exception:
        logger.exception("Failed to toggle admin for %s", user_id)
        return jsonify({"status": "failed", "message": "DB error"}), 500


@app.route("/admin/stats")
@admin_required
def admin_stats():
    """Return counts used by dashboard (users, conversations, journals, moods)."""
    out = {
        "users": 0,
        "conversations": 0,
        "active_users": 0, 
        "journals": 0,
        "moods": 0,
    }

    # ---- Users ----
    try:
        conn = get_db(USER_DB)
        if conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) AS cnt FROM users")
            out["users"] = c.fetchone()["cnt"]
    except Exception:
        logger.exception("Failed to count users")
    
        # ---- Active Users ----
    try:
        conn = get_db(USER_DB)
        if conn:
            c = conn.cursor()
            c.execute(
                "SELECT COUNT(*) AS cnt FROM users WHERE last_login IS NOT NULL"
            )
            out["active_users"] = c.fetchone()["cnt"]
    except Exception:
        logger.exception("Failed to count active users")

    # ---- Conversations ----
    try:
        conn = get_db(CONV_DB)
        if conn:
            c = conn.cursor()
            c.execute(
                "SELECT COUNT(*) AS cnt FROM conversations WHERE title != '__current__'"
            )
            out["conversations"] = c.fetchone()["cnt"]
    except Exception:
        logger.exception("Failed to count conversations")

    # ---- Journals ----
    try:
        conn = get_db(JOURNAL_DB)
        if conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) AS cnt FROM journal_entries")
            out["journals"] = c.fetchone()["cnt"]
    except Exception:
        logger.exception("Failed to count journals")

    # ---- Mood logs ----
    try:
        conn = get_db(MOOD_DB)
        if conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) AS cnt FROM mood_logs")
            out["moods"] = c.fetchone()["cnt"]
    except Exception:
        logger.exception("Failed to count mood logs")

    return jsonify(out)

@app.route("/admin/health")
@admin_required
def admin_health():
    try:
        conn = _postgres_connection()
        conn.execute("SELECT 1")
        conn.close()

        return jsonify({
            "status": "ok"
        })

    except:
        return jsonify({
            "status": "error"
        })


@app.route("/admin/journals_json")
@admin_required
def admin_journals_json():
    """Return journal entries as JSON (date, content)"""
    try:
        conn = get_db(JOURNAL_DB)
        if not conn:
            return jsonify([])
        c = conn.cursor()
        c.execute("SELECT id, user_id, date, content FROM journal_entries ORDER BY id DESC")
        rows = c.fetchall()
        return jsonify([{"id": r["id"], "user_id": r["user_id"], "date": r["date"], "content": r["content"]} for r in rows])
    except Exception:
        logger.exception("Failed to return journals JSON")
        return jsonify([])


@app.route("/admin/mood_json")
@admin_required
def admin_mood_json():
    """Return mood logs as JSON (date, mood, message)"""
    try:
        conn = get_db(MOOD_DB)
        if not conn:
            return jsonify([])
        c = conn.cursor()
        c.execute("SELECT id, user_id, date, mood, message FROM mood_logs ORDER BY id DESC")
        rows = c.fetchall()
        return jsonify([{"id": r["id"], "user_id": r["user_id"], "date": r["date"], "mood": r["mood"], "message": r["message"]} for r in rows])
    except Exception:
        logger.exception("Failed to return mood JSON")
        return jsonify([])


@app.route("/")
def home():

    is_logged_in = bool(session.get("user_id"))
    user = current_user()
    username = get_display_name(user)

    return render_template(
        "home.html",
        is_logged_in=is_logged_in,
        username=username
    )
    
@app.route("/index")
@login_required
def index():
    show_welcome = not session.get("welcome_shown", False)
    session["welcome_shown"] = True
    
    user = current_user()
    user_name = get_display_name(user)

    return render_template(
        "index.html",
        show_welcome=show_welcome,
        user_name=user_name
    )

@app.route("/set_consent", methods=["POST"])
def set_consent():
    data = request.get_json(silent=True) or {}
    allow = bool(data.get("allow", False))
    session["allow_remote_processing"] = allow
    return jsonify({"status": "ok", "allow_remote_processing": allow})

@app.route("/chat", methods=["POST"])
@csrf.exempt
@login_required
@limiter.limit("40 per minute")
def chat():
    data = request.get_json(silent=True) or {}
    message = safe_trim(data.get("message", ""))
    if not message:
        return jsonify(
            {
                "reply": "That last message looked empty — what would you like to share with me?",
                "action": None,
            }
        )

    conv_id = session.get("conv_id")
    allow_remote_processing = session.get("allow_remote_processing", True)

    try:
        history = get_history_by_conv_id(conv_id)
    except Exception:
        logger.exception("Failed to load history; creating a new conversation")
        conv_id = create_empty_conversation()
        session["conv_id"] = conv_id
        history = []

    history.append({"role": "user", "content": message, "ts": now()})

    reply_text, action = generate_reply_with_context(
        history, conv_id=conv_id, allow_remote_processing=allow_remote_processing
    )

    history.append({"role": "model", "content": reply_text, "ts": now()})

    try:
        save_history_by_conv_id(conv_id, history)
    except Exception:
        logger.exception("Failed to save history for conv_id=%s", conv_id)

    if action and action.get("type") == "crisis":
        try:
            logger.warning(
                "CRISIS_DETECTED conv_id=%s resources=%s text=%s",
                conv_id,
                json.dumps(action.get("resources")),
                message[:200],
            )
        except Exception:
            logger.exception("Failed logging crisis incident")

    if action and action.get("type") == "inline_breathing":
        try:
            logger.info(
                "INLINE_BREATHING conv_id=%s hint=%s text=%s",
                conv_id,
                action.get("severity_hint"),
                message[:200],
            )
        except Exception:
            logger.exception("Failed logging breathing event")

    return jsonify({"reply": reply_text, "action": action})


@app.route("/reset_session")
@login_required
def reset_session():

    conv_id = session.get("conv_id")

    try:
        if conv_id:
            delete_conversation(conv_id)

    except Exception:
        logger.exception("Error deleting conv on reset")

    # Create new conversation safely
    new_conv = create_empty_conversation()

    if new_conv:
        session["conv_id"] = new_conv
    else:
        logger.error("Failed to create new conversation during reset")

    return jsonify({"status": "reset"})

@app.route("/get_current_session")
@login_required
def get_current_session():
    conv_id = session.get("conv_id")
    try:
        history = get_history_by_conv_id(conv_id)
    except Exception:
        logger.exception("Error loading current session")
        history = []
    return jsonify(ok=True, history=history)

@app.route("/get_current_conversation")
@login_required
def get_current_conversation():

    conv_id = session.get("conv_id")

    if not conv_id:
        return jsonify(ok=False, message="No active conversation")

    try:
        history = get_history_by_conv_id(conv_id)

        if not history:
            return jsonify(ok=False, message="Nothing to export")

        return jsonify(ok=True, history=history)

    except Exception:
        logger.exception("Error fetching current conversation")
        return jsonify(ok=False, message="Export failed")
# -------- Conversations CRUD --------
@app.route("/save_conversation", methods=["POST"])
@login_required
def save_conversation():
    conv_id = session.get("conv_id")
    if not conv_id:
        return jsonify(ok=False, message="Nothing to save yet")

    data = request.get_json(silent=True) or {}
    title = data.get("title", "").strip()

    if not title:
        return jsonify(ok=False, message="Please provide a title")

    history = get_history_by_conv_id(conv_id)
    if not history:
        return jsonify(ok=False, message="Nothing to save yet")

    db = get_db(CONV_DB)
    db.execute(
        """
        UPDATE conversations
        SET title = ?, created_at = CURRENT_TIMESTAMP
        WHERE id = ? AND user_id = ?
        """,
        (title, conv_id, session["user_id"]),
    )
    db.commit()

    return jsonify(ok=True, message="Chat saved")

@app.route("/get_conversations")
@login_required
def get_conversations():
    db = get_db(CONV_DB)

    rows = db.execute(
        """
        SELECT id, title, created_at
        FROM conversations
        WHERE user_id = ?
        ORDER BY created_at DESC
        """,
        (session["user_id"],),
    ).fetchall()

    chats = [
        {
            "id": row["id"],
            "title": row["title"],
            "created_at": row["created_at"],
        }
        for row in rows
        if row["title"] and row["title"] != "__current__"
    ]

    return jsonify(ok=True, chats=chats)

@app.route("/load_conversation/<int:chat_id>")
@login_required
def load_conversation(chat_id):
    db = get_db(CONV_DB)

    row = db.execute(
        """
        SELECT id, history
        FROM conversations
        WHERE id = ? AND user_id = ?
        """,
        (chat_id, session["user_id"]),
    ).fetchone()

    if not row:
        return jsonify(ok=False, message="Chat not found")

    try:
        history = json.loads(row["history"]) if row["history"] else []
    except Exception:
        history = []

    session["conv_id"] = row["id"]
    return jsonify(ok=True, history=history)



@app.route("/delete_conversation/<int:chat_id>", methods=["DELETE"])
@login_required
def delete_conversation_route(chat_id):
    conn = get_db(CONV_DB)
    if not conn:
        return jsonify({"status": "failed"}), 500

    c = conn.cursor()
    c.execute(
        "DELETE FROM conversations WHERE id = ? AND user_id = ?",
        (chat_id, session.get("user_id"))
    )
    conn.commit()

    return jsonify({"status": "deleted"})



@app.route("/rename_conversation/<int:chat_id>", methods=["POST"])
@login_required
def rename_conversation(chat_id):
    data = request.get_json(silent=True) or {}
    title = data.get("title", "").strip()

    if not title:
        return jsonify(ok=False, message="Title cannot be empty")

    db = get_db(CONV_DB)
    db.execute(
        """
        UPDATE conversations
        SET title = ?
        WHERE id = ? AND user_id = ?
        """,
        (title, chat_id, session["user_id"]),
    )
    db.commit()

    return jsonify(ok=True, message="Chat renamed")




@app.route("/search_journals", methods=["GET"])
@login_required
def search_journals():
    query = request.args.get("q", "").strip()
    conn = get_db(JOURNAL_DB)
    if not conn:
        return jsonify([])

    c = conn.cursor()

    if query:
        c.execute(
            """
            SELECT date, content
            FROM journal_entries
            WHERE user_id = ? AND content LIKE ?
            ORDER BY id DESC
            """,
            (session["user_id"], f"%{query}%"),
        )
    else:
        c.execute(
            """
            SELECT date, content
            FROM journal_entries
            WHERE user_id = ?
            ORDER BY id DESC
            """,
            (session["user_id"],),
        )

    results = c.fetchall()
    return jsonify([[r["date"], r["content"]] for r in results])


@app.route("/export_journal")
@login_required
def export_journal():
    conn = get_db(JOURNAL_DB)
    if not conn:
        text_data = "No journal entries available."
    else:
        c = conn.cursor()
        c.execute(
    "SELECT date, content FROM journal_entries WHERE user_id = ? ORDER BY id DESC",
    (session["user_id"],)
)

        rows = c.fetchall()
        text_data = "\n\n".join(
            [f"{row['date']}:\n{row['content']}" for row in rows]
        )
    return Response(
        text_data,
        mimetype="text/plain",
        headers={"Content-Disposition": "attachment;filename=journal.txt"},
    )

@app.route("/api/journals/<int:entry_id>", methods=["DELETE"])
@login_required
def delete_journal_entry(entry_id):
    conn = get_db(JOURNAL_DB)
    if not conn:
        return jsonify(ok=False, message="DB unavailable"), 500

    cur = conn.cursor()
    cur.execute(
        """
        DELETE FROM journal_entries
        WHERE id = ? AND user_id = ?
        """,
        (entry_id, session["user_id"]),
    )
    conn.commit()

    if cur.rowcount == 0:
        return jsonify(ok=False, message="Entry not found"), 404

    return jsonify(ok=True)


@app.route("/export_chat")
@login_required
def export_chat():
    conv_id = session.get("conv_id")
    history = get_history_by_conv_id(conv_id)
    if not history:
        text_data = "No chat history available for this session."
    else:
        text_data = "\n\n".join(
            [f"{m['role'].capitalize()}: {m['content']}" for m in history]
        )
    return Response(
        text_data,
        mimetype="text/plain",
        headers={"Content-Disposition": "attachment;filename=chat_history.txt"},
    )

@app.route("/breathing")
@login_required
def breathing():
    return render_template("breathing.html")

@app.route("/history")
@login_required
def history():
    user_id = session.get("user_id")

    # ---- Mood logs (user-scoped) ----
    try:
        conn1 = get_db(MOOD_DB)
        if conn1:
            c1 = conn1.cursor()
            c1.execute(
                "SELECT date, mood, message FROM mood_logs WHERE user_id = ? ORDER BY id DESC",
                (user_id,)
            )
            mood_logs = c1.fetchall()
        else:
            mood_logs = []
    except Exception:
        logger.exception("❌ Mood DB error")
        mood_logs = []

    # ---- Journal entries (user-scoped) ----
    try:
        conn2 = get_db(JOURNAL_DB)
        if conn2:
            c2 = conn2.cursor()
            c2.execute(
                "SELECT date, content FROM journal_entries WHERE user_id = ? ORDER BY id DESC",
                (user_id,)
            )
            journal_entries = c2.fetchall()
        else:
            journal_entries = []
    except Exception:
        logger.exception("❌ Journal DB error")
        journal_entries = []

    mood_list = [(r["date"], r["mood"], r["message"]) for r in mood_logs]
    journal_list = [(r["date"], r["content"]) for r in journal_entries]

    return render_template(
        "history.html",
        mood_logs=mood_list,
        journal_entries=journal_list
    )



@app.route("/api/history/moods")
@login_required
def api_history_moods():
    db = get_db(MOOD_DB)
    user_id = current_user()["id"]

    rows = db.execute(
        """
        SELECT date, mood
        FROM mood_logs
        WHERE user_id = ?
        ORDER BY date ASC
        """,
        (user_id,),
    ).fetchall()

    return jsonify([
        {
            "date": r["date"],
            "mood": r["mood"]
        }
        for r in rows
    ])

@app.route("/api/history/summary")
@login_required
def api_history_summary():
    user_id = current_user()["id"]

    db_journal = get_db(JOURNAL_DB)
    db_conv = get_db(CONV_DB)
    db_mood = get_db(MOOD_DB)

    journal_count = db_journal.execute(
        "SELECT COUNT(*) FROM journal_entries WHERE user_id = ?",
        (user_id,)
    ).fetchone()[0]

    chat_count = db_conv.execute(
        "SELECT COUNT(*) FROM conversations WHERE user_id = ?",
        (user_id,)
    ).fetchone()[0]

    mood_count = db_mood.execute(
        "SELECT COUNT(*) FROM mood_logs WHERE user_id = ?",
        (user_id,)
    ).fetchone()[0]

    return jsonify({
        "journal_count": journal_count,
        "chat_count": chat_count,
        "mood_count": mood_count
    })


@app.route("/pick-a-peace")
@login_required
def pick_a_peace():
    return render_template("pick_a_peace.html")

@app.route("/calm-corner")
@login_required
def calm_corner():
    return render_template("calm-corner.html")

@app.route("/ebooks")
@login_required
def ebooks():
    return render_template("ebooks.html")

# -------------------- Run --------------------
if __name__ == "__main__":
    setup_databases()
    port = int(os.environ.get("PORT", 5000))
    # In production use a WSGI server such as gunicorn and set SESSION_COOKIE_SECURE=True
    app.run(host="0.0.0.0", port=port)
