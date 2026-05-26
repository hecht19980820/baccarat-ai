
from flask import Flask, render_template, request, jsonify, redirect, session
from datetime import datetime, timedelta
import sqlite3
import os

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "baccarat_admin_secret_2026")
DB_PATH = os.environ.get("DB_PATH", "baccarat_system.db")

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "Baccarat2026!")

DG_TABLES = ["RB01", "RB02", "RB03", "RB04", "RB05", "RB06", "RB07"]
MT_TABLES = ["1", "2", "3", "3A", "5", "6", "7", "8", "9", "10", "11", "12", "13", "13A", "15"]

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS agents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        display_name TEXT DEFAULT '',
        status TEXT DEFAULT 'active',
        created_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS players (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        display_name TEXT DEFAULT '',
        agent_id INTEGER,
        expire_at TEXT NOT NULL,
        role TEXT DEFAULT 'player',
        status TEXT DEFAULT 'active',
        created_at TEXT NOT NULL,
        FOREIGN KEY(agent_id) REFERENCES agents(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS game_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        table_no TEXT NOT NULL,
        result TEXT NOT NULL,
        card_pattern TEXT DEFAULT '',
        is_manual INTEGER DEFAULT 0,
        prediction_before TEXT DEFAULT '',
        counted_prediction INTEGER DEFAULT 0,
        is_correct INTEGER DEFAULT NULL,
        created_by TEXT DEFAULT '',
        created_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS bets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id INTEGER,
        source TEXT NOT NULL,
        table_no TEXT NOT NULL,
        bet_side TEXT NOT NULL,
        amount REAL DEFAULT 0,
        result TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        FOREIGN KEY(player_id) REFERENCES players(id)
    )
    """)

    # default sample agent/player so the page has data
    cur.execute("SELECT COUNT(*) AS c FROM agents")
    if cur.fetchone()["c"] == 0:
        cur.execute(
            "INSERT INTO agents(username,password,display_name,status,created_at) VALUES(?,?,?,?,?)",
            ("agent001", "123456", "預設代理", "active", now())
        )

    cur.execute("SELECT COUNT(*) AS c FROM players")
    if cur.fetchone()["c"] == 0:
        agent = cur.execute("SELECT id FROM agents WHERE username='agent001'").fetchone()
        expire = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        cur.execute(
            "INSERT INTO players(username,password,display_name,agent_id,expire_at,role,status,created_at) VALUES(?,?,?,?,?,?,?,?)",
            ("player001", "123456", "預設玩家", agent["id"] if agent else None, expire, "player", "active", now())
        )

    conn.commit()
    conn.close()

init_db()

def admin_required():
    return bool(session.get("admin_logged_in"))

@app.route("/")
def index():
    return render_template("index.html", dg_tables=DG_TABLES, mt_tables=MT_TABLES)

@app.route("/login", methods=["GET", "POST"])
def player_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        conn = connect()
        player = conn.execute("SELECT * FROM players WHERE username=? AND password=?", (username, password)).fetchone()
        conn.close()

        if player and player["status"] == "active" and player["expire_at"] >= datetime.now().strftime("%Y-%m-%d"):
            session["player_id"] = player["id"]
            session["player_username"] = player["username"]
            return redirect("/")
        return render_template("login.html", error="帳號、密碼錯誤，或會員已到期/停用")

    return render_template("login.html")

@app.route("/player-logout")
def player_logout():
    session.pop("player_id", None)
    session.pop("player_username", None)
    return redirect("/login")

@app.route("/admin-login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        if username == ADMIN_USER and password == ADMIN_PASS:
            session["admin_logged_in"] = True
            session["admin_user"] = username
            return redirect("/admin")
        return render_template("admin_login.html", error="管理員帳號或密碼錯誤")
    return render_template("admin_login.html")

@app.route("/admin-logout")
def admin_logout():
    session.clear()
    return redirect("/admin-login")

@app.route("/admin")
def admin():
    if not admin_required():
        return redirect("/admin-login")

    conn = connect()
    agents = conn.execute("SELECT * FROM agents ORDER BY id DESC").fetchall()
    players = conn.execute("""
        SELECT p.*, a.username AS agent_username
        FROM players p
        LEFT JOIN agents a ON a.id = p.agent_id
        ORDER BY p.id DESC
    """).fetchall()

    total_records = conn.execute("SELECT COUNT(*) AS c FROM game_records").fetchone()["c"]
    manual_records = conn.execute("SELECT COUNT(*) AS c FROM game_records WHERE is_manual=1").fetchone()["c"]
    prediction_count = conn.execute("SELECT COUNT(*) AS c FROM game_records WHERE counted_prediction=1").fetchone()["c"]
    correct_count = conn.execute("SELECT COUNT(*) AS c FROM game_records WHERE counted_prediction=1 AND is_correct=1").fetchone()["c"]
    table_stats = conn.execute("""
        SELECT source, table_no,
               COUNT(*) AS total,
               SUM(CASE WHEN result='莊' THEN 1 ELSE 0 END) AS banker,
               SUM(CASE WHEN result='閒' THEN 1 ELSE 0 END) AS player,
               SUM(CASE WHEN result='和' THEN 1 ELSE 0 END) AS tie,
               SUM(CASE WHEN counted_prediction=1 THEN 1 ELSE 0 END) AS predict_total,
               SUM(CASE WHEN counted_prediction=1 AND is_correct=1 THEN 1 ELSE 0 END) AS predict_correct
        FROM game_records
        GROUP BY source, table_no
        ORDER BY source, table_no
    """).fetchall()
    recent_records = conn.execute("SELECT * FROM game_records ORDER BY id DESC LIMIT 50").fetchall()
    conn.close()

    hit_rate = round(correct_count / prediction_count * 100, 1) if prediction_count else 0

    return render_template(
        "admin.html",
        agents=agents,
        players=players,
        total_records=total_records,
        manual_records=manual_records,
        prediction_count=prediction_count,
        correct_count=correct_count,
        hit_rate=hit_rate,
        table_stats=table_stats,
        recent_records=recent_records,
        dg_tables=DG_TABLES,
        mt_tables=MT_TABLES
    )

@app.route("/api/agents", methods=["POST"])
def create_agent():
    if not admin_required():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.json or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    display_name = data.get("display_name", "").strip()
    status = data.get("status", "active")

    if not username or not password:
        return jsonify({"ok": False, "error": "代理帳號與密碼必填"})

    try:
        conn = connect()
        conn.execute(
            "INSERT INTO agents(username,password,display_name,status,created_at) VALUES(?,?,?,?,?)",
            (username, password, display_name, status, now())
        )
        conn.commit()
        conn.close()
        return jsonify({"ok": True})
    except sqlite3.IntegrityError:
        return jsonify({"ok": False, "error": "代理帳號已存在"})

@app.route("/api/agents/<int:agent_id>", methods=["PUT", "DELETE"])
def update_delete_agent(agent_id):
    if not admin_required():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    conn = connect()
    if request.method == "DELETE":
        conn.execute("UPDATE players SET agent_id=NULL WHERE agent_id=?", (agent_id,))
        conn.execute("DELETE FROM agents WHERE id=?", (agent_id,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})

    data = request.json or {}
    conn.execute(
        "UPDATE agents SET username=?, password=?, display_name=?, status=? WHERE id=?",
        (
            data.get("username", "").strip(),
            data.get("password", "").strip(),
            data.get("display_name", "").strip(),
            data.get("status", "active"),
            agent_id
        )
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/players", methods=["POST"])
def create_player():
    if not admin_required():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.json or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    display_name = data.get("display_name", "").strip()
    agent_id = data.get("agent_id") or None
    expire_at = data.get("expire_at", "").strip()
    role = data.get("role", "player")
    status = data.get("status", "active")

    if not username or not password or not expire_at:
        return jsonify({"ok": False, "error": "玩家帳號、密碼、到期日必填"})

    try:
        conn = connect()
        conn.execute(
            "INSERT INTO players(username,password,display_name,agent_id,expire_at,role,status,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (username, password, display_name, agent_id, expire_at, role, status, now())
        )
        conn.commit()
        conn.close()
        return jsonify({"ok": True})
    except sqlite3.IntegrityError:
        return jsonify({"ok": False, "error": "玩家帳號已存在"})

@app.route("/api/players/<int:player_id>", methods=["PUT", "DELETE"])
def update_delete_player(player_id):
    if not admin_required():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    conn = connect()
    if request.method == "DELETE":
        conn.execute("DELETE FROM bets WHERE player_id=?", (player_id,))
        conn.execute("DELETE FROM players WHERE id=?", (player_id,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})

    data = request.json or {}
    conn.execute(
        """UPDATE players
           SET username=?, password=?, display_name=?, agent_id=?, expire_at=?, role=?, status=?
           WHERE id=?""",
        (
            data.get("username", "").strip(),
            data.get("password", "").strip(),
            data.get("display_name", "").strip(),
            data.get("agent_id") or None,
            data.get("expire_at", "").strip(),
            data.get("role", "player"),
            data.get("status", "active"),
            player_id
        )
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/table-data")
def table_data():
    source = request.args.get("source", "DG")
    table_no = request.args.get("table_no", DG_TABLES[0])
    conn = connect()
    rows = conn.execute(
        "SELECT * FROM game_records WHERE source=? AND table_no=? ORDER BY id ASC",
        (source, table_no)
    ).fetchall()
    conn.close()

    records = [dict(r) for r in rows]
    return jsonify({"ok": True, "records": records, "ai": calculate_ai(records)})

def calculate_ai(records):
    if not records:
        return {
            "suggest": "觀察",
            "confidence": 0,
            "trend": "資料不足",
            "tie_alert": False,
            "lucky6_alert": False,
            "reason": "目前資料不足，先觀察。"
        }

    recent = records[-20:]
    last10 = records[-10:]
    banker = sum(1 for r in recent if r["result"] == "莊")
    player = sum(1 for r in recent if r["result"] == "閒")
    tie = sum(1 for r in recent if r["result"] == "和")
    lucky6_like = sum(1 for r in recent if "6" in (r["card_pattern"] or "") or "幸運6" in (r["card_pattern"] or ""))

    if banker > player:
        suggest = "莊"
        confidence = min(88, 50 + (banker - player) * 5 + len(recent))
        trend = "近期偏莊"
    elif player > banker:
        suggest = "閒"
        confidence = min(88, 50 + (player - banker) * 5 + len(recent))
        trend = "近期偏閒"
    else:
        suggest = "觀察"
        confidence = 50
        trend = "莊閒接近"

    tie_rate_recent = tie / max(1, len(recent))
    tie_alert = tie_rate_recent >= 0.15 or (len(last10) >= 5 and sum(1 for r in last10 if r["result"] == "和") >= 2)
    lucky6_alert = lucky6_like >= 3

    reason = f"依最近{len(recent)}局、莊{banker}、閒{player}、和{tie}綜合判斷。"
    return {
        "suggest": suggest,
        "confidence": round(confidence, 1),
        "trend": trend,
        "tie_alert": tie_alert,
        "lucky6_alert": lucky6_alert,
        "reason": reason
    }

@app.route("/api/add-record", methods=["POST"])
def add_record():
    data = request.json or {}
    source = data.get("source", "DG")
    table_no = data.get("table_no", "")
    result = data.get("result", "")
    card_pattern = data.get("card_pattern", "")
    is_manual = int(data.get("is_manual", 0))
    prediction_before = data.get("prediction_before", "")
    counted_prediction = 0 if is_manual else int(data.get("counted_prediction", 1))
    is_correct = None

    if counted_prediction and prediction_before:
        is_correct = 1 if prediction_before == result else 0

    if result not in ["莊", "閒", "和"] and not is_manual:
        return jsonify({"ok": False, "error": "結果錯誤"})

    conn = connect()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO game_records(
            source, table_no, result, card_pattern, is_manual,
            prediction_before, counted_prediction, is_correct, created_by, created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?)
    """, (
        source, table_no, result, card_pattern, is_manual,
        prediction_before, counted_prediction, is_correct,
        session.get("player_username", "guest"), now()
    ))
    conn.commit()
    record_id = cur.lastrowid

    rows = conn.execute(
        "SELECT * FROM game_records WHERE source=? AND table_no=? ORDER BY id ASC",
        (source, table_no)
    ).fetchall()
    conn.close()

    records = [dict(r) for r in rows]
    return jsonify({"ok": True, "record_id": record_id, "ai": calculate_ai(records)})

@app.route("/api/undo", methods=["POST"])
def undo():
    data = request.json or {}
    source = data.get("source", "DG")
    table_no = data.get("table_no", "")

    conn = connect()
    row = conn.execute(
        "SELECT id FROM game_records WHERE source=? AND table_no=? ORDER BY id DESC LIMIT 1",
        (source, table_no)
    ).fetchone()

    if not row:
        conn.close()
        return jsonify({"ok": False, "error": "沒有可撤回資料"})

    conn.execute("DELETE FROM game_records WHERE id=?", (row["id"],))
    conn.commit()

    rows = conn.execute(
        "SELECT * FROM game_records WHERE source=? AND table_no=? ORDER BY id ASC",
        (source, table_no)
    ).fetchall()
    conn.close()

    records = [dict(r) for r in rows]
    return jsonify({"ok": True, "deleted_id": row["id"], "records": records, "ai": calculate_ai(records)})

@app.route("/api/bet", methods=["POST"])
def add_bet():
    data = request.json or {}
    conn = connect()
    conn.execute("""
        INSERT INTO bets(player_id, source, table_no, bet_side, amount, result, created_at)
        VALUES(?,?,?,?,?,?,?)
    """, (
        session.get("player_id"),
        data.get("source", "DG"),
        data.get("table_no", ""),
        data.get("bet_side", ""),
        float(data.get("amount", 0) or 0),
        data.get("result", ""),
        now()
    ))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
