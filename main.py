
from flask import Flask, render_template, request, jsonify, redirect, session
from datetime import datetime, timedelta
import sqlite3
import os
import math

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "baccarat_admin_secret_2026")
DB_PATH = os.environ.get("DB_PATH", "baccarat_system.db")

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "Baccarat2026!")

DG_TABLES = ["RB01", "RB02", "RB03", "RB04", "RB05", "RB06", "RB07"]
MT_TABLES = ["1", "2", "3", "3A", "5", "6", "7", "8", "9", "10", "11", "12", "13", "13A", "15"]

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def today():
    return datetime.now().strftime("%Y-%m-%d")

def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def safe_float(v, default=0):
    try:
        return float(v)
    except Exception:
        return default

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
        ai_confidence_before REAL DEFAULT 0,
        ai_reason_before TEXT DEFAULT '',
        lucky6_flag INTEGER DEFAULT 0,
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

    cur.execute("""
    CREATE TABLE IF NOT EXISTS ai_weights (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        table_no TEXT NOT NULL,
        banker_weight REAL DEFAULT 1,
        player_weight REAL DEFAULT 1,
        tie_weight REAL DEFAULT 1,
        lucky6_weight REAL DEFAULT 1,
        total_trained INTEGER DEFAULT 0,
        last_suggest TEXT DEFAULT '',
        last_confidence REAL DEFAULT 0,
        updated_at TEXT NOT NULL,
        UNIQUE(source, table_no)
    )
    """)

    # SQLite migration-safe columns
    existing_cols = [r["name"] for r in cur.execute("PRAGMA table_info(game_records)").fetchall()]
    migrations = {
        "ai_confidence_before": "ALTER TABLE game_records ADD COLUMN ai_confidence_before REAL DEFAULT 0",
        "ai_reason_before": "ALTER TABLE game_records ADD COLUMN ai_reason_before TEXT DEFAULT ''",
        "lucky6_flag": "ALTER TABLE game_records ADD COLUMN lucky6_flag INTEGER DEFAULT 0",
    }
    for col, sql in migrations.items():
        if col not in existing_cols:
            cur.execute(sql)

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

    for src, tables in [("DG", DG_TABLES), ("MT", MT_TABLES)]:
        for t in tables:
            cur.execute("""
            INSERT OR IGNORE INTO ai_weights(source, table_no, banker_weight, player_weight, tie_weight, lucky6_weight, total_trained, updated_at)
            VALUES(?,?,?,?,?,?,?,?)
            """, (src, t, 1, 1, 1, 1, 0, now()))

    conn.commit()
    conn.close()

init_db()

def admin_required():
    return bool(session.get("admin_logged_in"))

def detect_lucky6(text):
    s = str(text or "")
    return 1 if ("幸運6" in s or "幸运6" in s or "lucky6" in s.lower() or "lucky 6" in s.lower() or re.search(r'(^|[^0-9])6([^0-9]|$)', s)) else 0

def get_records(conn, source, table_no):
    rows = conn.execute(
        "SELECT * FROM game_records WHERE source=? AND table_no=? ORDER BY id ASC",
        (source, table_no)
    ).fetchall()
    return [dict(r) for r in rows]

def ensure_weight(conn, source, table_no):
    row = conn.execute("SELECT * FROM ai_weights WHERE source=? AND table_no=?", (source, table_no)).fetchone()
    if not row:
        conn.execute("""
        INSERT INTO ai_weights(source, table_no, banker_weight, player_weight, tie_weight, lucky6_weight, total_trained, updated_at)
        VALUES(?,?,?,?,?,?,?,?)
        """, (source, table_no, 1, 1, 1, 1, 0, now()))
        conn.commit()
        row = conn.execute("SELECT * FROM ai_weights WHERE source=? AND table_no=?", (source, table_no)).fetchone()
    return dict(row)

def streak_score(records):
    if not records:
        return {"side": "", "count": 0, "jump": 0}
    filtered = [r["result"] for r in records if r["result"] in ["莊", "閒"]]
    if not filtered:
        return {"side": "", "count": 0, "jump": 0}
    last = filtered[-1]
    count = 1
    for x in reversed(filtered[:-1]):
        if x == last:
            count += 1
        else:
            break
    jump = 0
    if len(filtered) >= 4:
        recent = filtered[-6:]
        jump = sum(1 for i in range(1, len(recent)) if recent[i] != recent[i-1])
    return {"side": last, "count": count, "jump": jump}

def calculate_ai(records, weight):
    """
    統計權重版 AI：
    - 使用全站共享資料庫中該桌資料
    - DG/MT、桌號獨立模型
    - 手動牌型納入趨勢與路型
    - 手動不算命中率，但會影響資料統計
    """
    n = len(records)
    if n == 0:
        return {
            "suggest": "觀察",
            "confidence": 0,
            "trend": "資料不足",
            "tie_alert": False,
            "lucky6_alert": False,
            "tie_rate": 0,
            "lucky6_rate": 0,
            "reason": "目前資料不足，先觀察。"
        }

    recent_n = 30
    recent = records[-recent_n:]
    recent10 = records[-10:]
    recent20 = records[-20:]

    b = sum(1 for r in recent if r["result"] == "莊")
    p = sum(1 for r in recent if r["result"] == "閒")
    t = sum(1 for r in recent if r["result"] == "和")
    total = max(1, len(recent))

    # weighted scores
    wb = safe_float(weight.get("banker_weight", 1), 1)
    wp = safe_float(weight.get("player_weight", 1), 1)
    wt = safe_float(weight.get("tie_weight", 1), 1)
    wl = safe_float(weight.get("lucky6_weight", 1), 1)

    s = streak_score(recent)
    banker_score = (b / total) * 100 * wb
    player_score = (p / total) * 100 * wp
    tie_score = (t / total) * 100 * wt

    # 路型微調：連莊/連閒給同方加權，跳路給反方一點權重
    if s["side"] == "莊" and s["count"] >= 2:
        banker_score += min(18, s["count"] * 4)
    if s["side"] == "閒" and s["count"] >= 2:
        player_score += min(18, s["count"] * 4)
    if s["jump"] >= 4 and s["side"] == "莊":
        player_score += 8
    if s["jump"] >= 4 and s["side"] == "閒":
        banker_score += 8

    # 和局提醒，不直接建議重押和，只做提醒
    tie_rate = t / total
    tie_recent10 = sum(1 for r in recent10 if r["result"] == "和") / max(1, len(recent10))
    tie_alert = tie_rate >= 0.14 or tie_recent10 >= 0.20

    # 幸運6偵測：牌型中包含幸運6/6
    lucky_count = sum(1 for r in recent if r.get("lucky6_flag") or detect_lucky6(r.get("card_pattern", "")))
    lucky6_rate = lucky_count / total
    lucky6_alert = (lucky6_rate * wl) >= 0.12 or lucky_count >= 3

    if banker_score > player_score + 3:
        suggest = "莊"
        edge = banker_score - player_score
    elif player_score > banker_score + 3:
        suggest = "閒"
        edge = player_score - banker_score
    else:
        suggest = "觀察"
        edge = abs(banker_score - player_score)

    confidence = 0 if suggest == "觀察" else min(88, max(52, 45 + edge + min(12, n / 20)))
    if n < 8:
        confidence = min(confidence, 58)

    if b > p:
        trend = "近期偏莊"
    elif p > b:
        trend = "近期偏閒"
    else:
        trend = "莊閒接近"

    reason = f"結合本桌最近{len(recent)}局、莊{b}、閒{p}、和{t}、權重莊{wb:.2f}/閒{wp:.2f}/和{wt:.2f}、路型連續與跳路綜合判斷。"

    return {
        "suggest": suggest,
        "confidence": round(confidence, 1),
        "trend": trend,
        "tie_alert": bool(tie_alert),
        "lucky6_alert": bool(lucky6_alert),
        "tie_rate": round(tie_rate * 100, 1),
        "lucky6_rate": round(lucky6_rate * 100, 1),
        "reason": reason
    }

def update_ai_weight(conn, source, table_no, result, prediction_before, is_manual, lucky6_flag):
    """
    自動權重學習：
    - 每桌獨立權重
    - 手動牌型納入路型資料，但不算預測命中率
    - 非手動且有 prediction_before 才調整命中權重
    """
    w = ensure_weight(conn, source, table_no)

    bw = safe_float(w["banker_weight"], 1)
    pw = safe_float(w["player_weight"], 1)
    tw = safe_float(w["tie_weight"], 1)
    lw = safe_float(w["lucky6_weight"], 1)
    trained = int(w["total_trained"] or 0)

    # 結果出現會給微幅統計學習，避免單一方向過度偏移
    if result == "莊":
        bw += 0.015
        pw = max(0.70, pw - 0.004)
    elif result == "閒":
        pw += 0.015
        bw = max(0.70, bw - 0.004)
    elif result == "和":
        tw += 0.025

    if lucky6_flag:
        lw += 0.03

    if not is_manual and prediction_before in ["莊", "閒", "和"]:
        trained += 1
        # 命中強化，失誤微降
        hit = prediction_before == result
        if prediction_before == "莊":
            bw += 0.03 if hit else -0.02
        elif prediction_before == "閒":
            pw += 0.03 if hit else -0.02
        elif prediction_before == "和":
            tw += 0.03 if hit else -0.02

    # clamp
    bw = min(2.2, max(0.65, bw))
    pw = min(2.2, max(0.65, pw))
    tw = min(2.2, max(0.65, tw))
    lw = min(2.5, max(0.70, lw))

    records = get_records(conn, source, table_no)
    ai = calculate_ai(records, {"banker_weight": bw, "player_weight": pw, "tie_weight": tw, "lucky6_weight": lw})

    conn.execute("""
    UPDATE ai_weights
    SET banker_weight=?, player_weight=?, tie_weight=?, lucky6_weight=?,
        total_trained=?, last_suggest=?, last_confidence=?, updated_at=?
    WHERE source=? AND table_no=?
    """, (bw, pw, tw, lw, trained, ai["suggest"], ai["confidence"], now(), source, table_no))

def recalc_weight_from_records(conn, source, table_no):
    """撤回後重新依歷史資料粗略重建該桌權重，避免撤回仍殘留學習。"""
    rows = get_records(conn, source, table_no)
    bw = pw = tw = lw = 1.0
    trained = 0
    for r in rows:
        result = r["result"]
        is_manual = int(r.get("is_manual") or 0)
        pred = r.get("prediction_before") or ""
        lucky = int(r.get("lucky6_flag") or 0)
        if result == "莊":
            bw += 0.015; pw = max(0.70, pw - 0.004)
        elif result == "閒":
            pw += 0.015; bw = max(0.70, bw - 0.004)
        elif result == "和":
            tw += 0.025
        if lucky:
            lw += 0.03
        if not is_manual and pred in ["莊", "閒", "和"]:
            trained += 1
            hit = pred == result
            if pred == "莊":
                bw += 0.03 if hit else -0.02
            elif pred == "閒":
                pw += 0.03 if hit else -0.02
            elif pred == "和":
                tw += 0.03 if hit else -0.02
        bw = min(2.2, max(0.65, bw))
        pw = min(2.2, max(0.65, pw))
        tw = min(2.2, max(0.65, tw))
        lw = min(2.5, max(0.70, lw))

    ai = calculate_ai(rows, {"banker_weight": bw, "player_weight": pw, "tie_weight": tw, "lucky6_weight": lw})
    conn.execute("""
    INSERT INTO ai_weights(source, table_no, banker_weight, player_weight, tie_weight, lucky6_weight, total_trained, last_suggest, last_confidence, updated_at)
    VALUES(?,?,?,?,?,?,?,?,?,?)
    ON CONFLICT(source, table_no) DO UPDATE SET
        banker_weight=excluded.banker_weight,
        player_weight=excluded.player_weight,
        tie_weight=excluded.tie_weight,
        lucky6_weight=excluded.lucky6_weight,
        total_trained=excluded.total_trained,
        last_suggest=excluded.last_suggest,
        last_confidence=excluded.last_confidence,
        updated_at=excluded.updated_at
    """, (source, table_no, bw, pw, tw, lw, trained, ai["suggest"], ai["confidence"], now()))

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
        if player and player["status"] == "active" and player["expire_at"] >= today():
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
        SELECT g.source, g.table_no,
               COUNT(*) AS total,
               SUM(CASE WHEN g.result='莊' THEN 1 ELSE 0 END) AS banker,
               SUM(CASE WHEN g.result='閒' THEN 1 ELSE 0 END) AS player,
               SUM(CASE WHEN g.result='和' THEN 1 ELSE 0 END) AS tie,
               SUM(CASE WHEN g.counted_prediction=1 THEN 1 ELSE 0 END) AS predict_total,
               SUM(CASE WHEN g.counted_prediction=1 AND g.is_correct=1 THEN 1 ELSE 0 END) AS predict_correct
        FROM game_records g
        GROUP BY g.source, g.table_no
        ORDER BY g.source, g.table_no
    """).fetchall()

    ai_weights = conn.execute("SELECT * FROM ai_weights ORDER BY source, table_no").fetchall()
    recent_records = conn.execute("SELECT * FROM game_records ORDER BY id DESC LIMIT 80").fetchall()
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
        ai_weights=ai_weights,
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
        conn.execute("INSERT INTO agents(username,password,display_name,status,created_at) VALUES(?,?,?,?,?)",
                     (username, password, display_name, status, now()))
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
        conn.commit(); conn.close()
        return jsonify({"ok": True})
    data = request.json or {}
    conn.execute("UPDATE agents SET username=?, password=?, display_name=?, status=? WHERE id=?",
                 (data.get("username","").strip(), data.get("password","").strip(),
                  data.get("display_name","").strip(), data.get("status","active"), agent_id))
    conn.commit(); conn.close()
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
        conn.execute("""
        INSERT INTO players(username,password,display_name,agent_id,expire_at,role,status,created_at)
        VALUES(?,?,?,?,?,?,?,?)
        """, (username, password, display_name, agent_id, expire_at, role, status, now()))
        conn.commit(); conn.close()
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
        conn.commit(); conn.close()
        return jsonify({"ok": True})
    data = request.json or {}
    conn.execute("""
    UPDATE players SET username=?, password=?, display_name=?, agent_id=?, expire_at=?, role=?, status=? WHERE id=?
    """, (data.get("username","").strip(), data.get("password","").strip(),
          data.get("display_name","").strip(), data.get("agent_id") or None,
          data.get("expire_at","").strip(), data.get("role","player"), data.get("status","active"), player_id))
    conn.commit(); conn.close()
    return jsonify({"ok": True})

@app.route("/api/table-data")
def table_data():
    source = request.args.get("source", "DG")
    table_no = request.args.get("table_no", DG_TABLES[0])
    conn = connect()
    weight = ensure_weight(conn, source, table_no)
    records = get_records(conn, source, table_no)
    ai = calculate_ai(records, weight)
    conn.close()
    return jsonify({"ok": True, "records": records, "ai": ai, "weight": weight})

@app.route("/api/add-record", methods=["POST"])
def add_record():
    data = request.json or {}
    source = data.get("source", "DG")
    table_no = data.get("table_no", "")
    result = data.get("result", "")
    card_pattern = data.get("card_pattern", "")
    is_manual = int(data.get("is_manual", 0))
    prediction_before = data.get("prediction_before", "")
    ai_confidence_before = safe_float(data.get("ai_confidence_before", 0), 0)
    ai_reason_before = data.get("ai_reason_before", "")
    counted_prediction = 0 if is_manual else int(data.get("counted_prediction", 1))
    lucky6_flag = detect_lucky6(card_pattern)
    is_correct = None

    if counted_prediction and prediction_before:
        is_correct = 1 if prediction_before == result else 0

    if result not in ["莊", "閒", "和"]:
        return jsonify({"ok": False, "error": "結果錯誤"})

    conn = connect()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO game_records(
            source, table_no, result, card_pattern, is_manual,
            prediction_before, counted_prediction, is_correct,
            ai_confidence_before, ai_reason_before, lucky6_flag,
            created_by, created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        source, table_no, result, card_pattern, is_manual,
        prediction_before, counted_prediction, is_correct,
        ai_confidence_before, ai_reason_before, lucky6_flag,
        session.get("player_username", "guest"), now()
    ))
    conn.commit()
    record_id = cur.lastrowid

    update_ai_weight(conn, source, table_no, result, prediction_before, is_manual, lucky6_flag)
    conn.commit()

    weight = ensure_weight(conn, source, table_no)
    records = get_records(conn, source, table_no)
    ai = calculate_ai(records, weight)
    conn.close()

    return jsonify({"ok": True, "record_id": record_id, "ai": ai, "weight": weight})

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
    recalc_weight_from_records(conn, source, table_no)
    conn.commit()

    weight = ensure_weight(conn, source, table_no)
    records = get_records(conn, source, table_no)
    ai = calculate_ai(records, weight)
    conn.close()

    return jsonify({"ok": True, "deleted_id": row["id"], "records": records, "ai": ai, "weight": weight})

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
    conn.commit(); conn.close()
    return jsonify({"ok": True})

@app.route("/api/reset-ai-weight", methods=["POST"])
def reset_ai_weight():
    if not admin_required():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    data = request.json or {}
    source = data.get("source")
    table_no = data.get("table_no")
    conn = connect()
    conn.execute("""
    UPDATE ai_weights
    SET banker_weight=1, player_weight=1, tie_weight=1, lucky6_weight=1, total_trained=0, last_suggest='', last_confidence=0, updated_at=?
    WHERE source=? AND table_no=?
    """, (now(), source, table_no))
    conn.commit(); conn.close()
    return jsonify({"ok": True})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
