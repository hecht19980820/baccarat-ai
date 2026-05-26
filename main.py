from flask import Flask, render_template, request, jsonify, redirect, session
import sqlite3, os, re
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "baccarat_phase2_secret")
DB_NAME = os.environ.get("DB_PATH", "baccarat_system.db")

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "Baccarat2026!")

DG_TABLES = ["RB01","RB02","RB03","RB04","RB05","RB06","RB07"]
MT_TABLES = ["1","2","3","3A","5","6","7","8","9","10","11","12","13","13A","15"]

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        expire_date TEXT,
        role TEXT DEFAULT 'player',
        status TEXT DEFAULT 'active',
        agent TEXT DEFAULT '',
        created_at TEXT DEFAULT ''
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS agents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        created_at TEXT DEFAULT ''
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS game_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT,
        table_no TEXT,
        result TEXT,
        pattern TEXT DEFAULT '',
        is_manual INTEGER DEFAULT 0,
        prediction TEXT DEFAULT '',
        ai_score REAL DEFAULT 0,
        is_correct INTEGER DEFAULT NULL,
        lucky6 INTEGER DEFAULT 0,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS ai_weights (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT,
        table_no TEXT,
        banker_weight REAL DEFAULT 1,
        player_weight REAL DEFAULT 1,
        tie_weight REAL DEFAULT 1,
        lucky6_weight REAL DEFAULT 1,
        trained_count INTEGER DEFAULT 0,
        updated_at TEXT,
        UNIQUE(category, table_no)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS bets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT DEFAULT '',
        category TEXT,
        table_no TEXT,
        bet_side TEXT,
        amount REAL DEFAULT 0,
        created_at TEXT
    )
    """)

    cur.execute("SELECT COUNT(*) c FROM users")
    if cur.fetchone()["c"] == 0:
        expire = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        cur.execute("INSERT INTO users(username,password,expire_date,role,status,agent,created_at) VALUES(?,?,?,?,?,?,?)",
                    ("player001","123456",expire,"player","active","agent001",now()))

    cur.execute("SELECT COUNT(*) c FROM agents")
    if cur.fetchone()["c"] == 0:
        cur.execute("INSERT INTO agents(username,password,created_at) VALUES(?,?,?)", ("agent001","123456",now()))

    for c, tables in [("DG", DG_TABLES), ("MT", MT_TABLES)]:
        for t in tables:
            cur.execute("""INSERT OR IGNORE INTO ai_weights(category,table_no,updated_at)
                           VALUES(?,?,?)""", (c,t,now()))

    conn.commit()
    conn.close()

init_db()

def admin_required():
    return bool(session.get("admin"))

def detect_lucky6(pattern):
    s = str(pattern or "").lower()
    return 1 if ("幸運6" in s or "幸运6" in s or "lucky6" in s or "lucky 6" in s or re.search(r"(^|[^0-9])6([^0-9]|$)", s)) else 0

def get_weight(conn, category, table_no):
    row = conn.execute("SELECT * FROM ai_weights WHERE category=? AND table_no=?", (category, table_no)).fetchone()
    if not row:
        conn.execute("INSERT OR IGNORE INTO ai_weights(category,table_no,updated_at) VALUES(?,?,?)", (category, table_no, now()))
        conn.commit()
        row = conn.execute("SELECT * FROM ai_weights WHERE category=? AND table_no=?", (category, table_no)).fetchone()
    return row

def get_records(conn, category, table_no):
    return conn.execute("SELECT * FROM game_records WHERE category=? AND table_no=? ORDER BY id ASC", (category, table_no)).fetchall()

def ai_analysis(category, table_no):
    conn = db()
    w = get_weight(conn, category, table_no)
    rows = get_records(conn, category, table_no)
    conn.close()

    if not rows:
        return {
            "suggest":"觀察","confidence":0,"trend":"資料不足",
            "reason":"目前資料不足，先觀察。",
            "tie_alert":False,"lucky6_alert":False,
            "tie_rate":0,"lucky6_rate":0
        }

    recent = rows[-30:]
    total = max(1, len(recent))
    banker = sum(1 for r in recent if r["result"] == "莊")
    player = sum(1 for r in recent if r["result"] == "閒")
    tie = sum(1 for r in recent if r["result"] == "和")
    lucky = sum(1 for r in recent if r["lucky6"] == 1)

    bw, pw, tw, lw = w["banker_weight"], w["player_weight"], w["tie_weight"], w["lucky6_weight"]
    banker_score = banker / total * 100 * bw
    player_score = player / total * 100 * pw

    # 連續路與跳路微調
    pure = [r["result"] for r in recent if r["result"] in ["莊","閒"]]
    if pure:
        last = pure[-1]
        streak = 1
        for x in reversed(pure[:-1]):
            if x == last: streak += 1
            else: break
        if streak >= 2:
            if last == "莊": banker_score += min(16, streak * 4)
            if last == "閒": player_score += min(16, streak * 4)

    if banker_score > player_score + 3:
        suggest = "莊"
        edge = banker_score - player_score
    elif player_score > banker_score + 3:
        suggest = "閒"
        edge = player_score - banker_score
    else:
        suggest = "觀察"
        edge = 0

    confidence = 0 if suggest == "觀察" else round(min(88, max(52, 45 + edge + min(12, len(rows)/20))), 1)
    trend = "近期偏莊" if banker > player else "近期偏閒" if player > banker else "莊閒接近"

    tie_rate = round(tie / total * 100, 1)
    lucky_rate = round(lucky / total * 100, 1)
    tie_alert = tie_rate >= 14 or sum(1 for r in recent[-10:] if r["result"]=="和") >= 2
    lucky6_alert = lucky_rate >= 12 or lucky >= 3

    return {
        "suggest":suggest,
        "confidence":confidence,
        "trend":trend,
        "reason":f"結合後台共享資料、本桌最近{total}局、莊{banker}、閒{player}、和{tie}、權重莊{bw:.2f}/閒{pw:.2f}/和{tw:.2f}。",
        "tie_alert":tie_alert,
        "lucky6_alert":lucky6_alert,
        "tie_rate":tie_rate,
        "lucky6_rate":lucky_rate
    }

def update_weight(category, table_no, result, prediction, is_manual, lucky6):
    conn = db()
    w = get_weight(conn, category, table_no)
    bw, pw, tw, lw = w["banker_weight"], w["player_weight"], w["tie_weight"], w["lucky6_weight"]
    trained = w["trained_count"] or 0

    if result == "莊":
        bw += 0.015
        pw = max(0.7, pw - 0.004)
    elif result == "閒":
        pw += 0.015
        bw = max(0.7, bw - 0.004)
    elif result == "和":
        tw += 0.025

    if lucky6:
        lw += 0.03

    if not is_manual and prediction in ["莊","閒","和"]:
        trained += 1
        hit = prediction == result
        if prediction == "莊": bw += 0.03 if hit else -0.02
        if prediction == "閒": pw += 0.03 if hit else -0.02
        if prediction == "和": tw += 0.03 if hit else -0.02

    bw = min(2.2, max(0.65, bw))
    pw = min(2.2, max(0.65, pw))
    tw = min(2.2, max(0.65, tw))
    lw = min(2.5, max(0.7, lw))

    conn.execute("""UPDATE ai_weights
                    SET banker_weight=?, player_weight=?, tie_weight=?, lucky6_weight=?, trained_count=?, updated_at=?
                    WHERE category=? AND table_no=?""",
                 (bw,pw,tw,lw,trained,now(),category,table_no))
    conn.commit()
    conn.close()

def rebuild_weight(category, table_no):
    conn = db()
    rows = get_records(conn, category, table_no)
    bw = pw = tw = lw = 1.0
    trained = 0
    for r in rows:
        if r["result"] == "莊":
            bw += 0.015; pw = max(0.7, pw - 0.004)
        elif r["result"] == "閒":
            pw += 0.015; bw = max(0.7, bw - 0.004)
        elif r["result"] == "和":
            tw += 0.025
        if r["lucky6"]:
            lw += 0.03
        if not r["is_manual"] and r["prediction"] in ["莊","閒","和"]:
            trained += 1
            hit = r["prediction"] == r["result"]
            if r["prediction"] == "莊": bw += 0.03 if hit else -0.02
            if r["prediction"] == "閒": pw += 0.03 if hit else -0.02
            if r["prediction"] == "和": tw += 0.03 if hit else -0.02
        bw = min(2.2, max(0.65, bw))
        pw = min(2.2, max(0.65, pw))
        tw = min(2.2, max(0.65, tw))
        lw = min(2.5, max(0.7, lw))
    conn.execute("""UPDATE ai_weights
                    SET banker_weight=?, player_weight=?, tie_weight=?, lucky6_weight=?, trained_count=?, updated_at=?
                    WHERE category=? AND table_no=?""",
                 (bw,pw,tw,lw,trained,now(),category,table_no))
    conn.commit()
    conn.close()

@app.route("/")
def index():
    return render_template("index.html", dg_tables=DG_TABLES, mt_tables=MT_TABLES)

@app.route("/admin-login", methods=["GET","POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("username") == ADMIN_USER and request.form.get("password") == ADMIN_PASS:
            session["admin"] = True
            return redirect("/admin")
        return render_template("admin_login.html", error="帳號或密碼錯誤")
    return render_template("admin_login.html")

@app.route("/logout")
@app.route("/admin-logout")
def logout():
    session.clear()
    return redirect("/admin-login")

@app.route("/admin")
def admin():
    if not admin_required():
        return redirect("/admin-login")

    conn = db()
    users = conn.execute("SELECT * FROM users ORDER BY id DESC").fetchall()
    agents = conn.execute("SELECT * FROM agents ORDER BY id DESC").fetchall()
    weights = conn.execute("SELECT * FROM ai_weights ORDER BY category, table_no").fetchall()
    records = conn.execute("SELECT * FROM game_records ORDER BY id DESC LIMIT 80").fetchall()

    total_records = conn.execute("SELECT COUNT(*) c FROM game_records").fetchone()["c"]
    manual_records = conn.execute("SELECT COUNT(*) c FROM game_records WHERE is_manual=1").fetchone()["c"]
    predict_count = conn.execute("SELECT COUNT(*) c FROM game_records WHERE prediction IN ('莊','閒','和') AND is_manual=0").fetchone()["c"]
    correct_count = conn.execute("SELECT COUNT(*) c FROM game_records WHERE is_correct=1").fetchone()["c"]
    hit_rate = round(correct_count / predict_count * 100, 1) if predict_count else 0

    table_stats = conn.execute("""
        SELECT category, table_no,
        COUNT(*) total,
        SUM(CASE WHEN result='莊' THEN 1 ELSE 0 END) banker,
        SUM(CASE WHEN result='閒' THEN 1 ELSE 0 END) player,
        SUM(CASE WHEN result='和' THEN 1 ELSE 0 END) tie_count,
        SUM(CASE WHEN prediction IN ('莊','閒','和') AND is_manual=0 THEN 1 ELSE 0 END) predicts,
        SUM(CASE WHEN is_correct=1 THEN 1 ELSE 0 END) corrects
        FROM game_records
        GROUP BY category, table_no
        ORDER BY category, table_no
    """).fetchall()
    conn.close()

    return render_template("admin.html", users=users, agents=agents, weights=weights, records=records,
                           total_records=total_records, manual_records=manual_records,
                           predict_count=predict_count, hit_rate=hit_rate, table_stats=table_stats)

@app.route("/add-user", methods=["POST"])
def add_user():
    if not admin_required(): return redirect("/admin-login")
    conn = db()
    try:
        conn.execute("""INSERT INTO users(username,password,expire_date,role,status,agent,created_at)
                        VALUES(?,?,?,?,?,?,?)""",
                     (request.form.get("username"), request.form.get("password"), request.form.get("expire_date"),
                      request.form.get("role"), request.form.get("status"), request.form.get("agent"), now()))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()
    return redirect("/admin")

@app.route("/delete-user/<int:user_id>")
def delete_user(user_id):
    if not admin_required(): return redirect("/admin-login")
    conn = db(); conn.execute("DELETE FROM users WHERE id=?", (user_id,)); conn.commit(); conn.close()
    return redirect("/admin")

@app.route("/add-agent", methods=["POST"])
def add_agent():
    if not admin_required(): return redirect("/admin-login")
    conn = db()
    try:
        conn.execute("INSERT INTO agents(username,password,created_at) VALUES(?,?,?)",
                     (request.form.get("username"), request.form.get("password"), now()))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()
    return redirect("/admin")

@app.route("/delete-agent/<int:agent_id>")
def delete_agent(agent_id):
    if not admin_required(): return redirect("/admin-login")
    conn = db(); conn.execute("DELETE FROM agents WHERE id=?", (agent_id,)); conn.commit(); conn.close()
    return redirect("/admin")

@app.route("/api/table")
def api_table():
    category = request.args.get("category","DG")
    table_no = request.args.get("table_no","RB01")
    conn = db()
    rows = conn.execute("SELECT * FROM game_records WHERE category=? AND table_no=? ORDER BY id ASC", (category,table_no)).fetchall()
    conn.close()
    return jsonify({"success":True, "records":[dict(r) for r in rows], "ai":ai_analysis(category,table_no)})

@app.route("/add-record", methods=["POST"])
def add_record():
    data = request.json or {}
    category = data.get("category","DG")
    table_no = data.get("table_no","RB01")
    result = data.get("result")
    pattern = data.get("pattern","")
    is_manual = 1 if data.get("is_manual",0) else 0

    ai = ai_analysis(category, table_no)
    prediction = "" if is_manual else ai["suggest"]
    ai_score = 0 if is_manual else ai["confidence"]
    lucky6 = detect_lucky6(pattern)
    is_correct = None
    if not is_manual and prediction in ["莊","閒","和"]:
        is_correct = 1 if prediction == result else 0

    conn = db()
    conn.execute("""INSERT INTO game_records(category,table_no,result,pattern,is_manual,prediction,ai_score,is_correct,lucky6,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?)""",
                 (category,table_no,result,pattern,is_manual,prediction,ai_score,is_correct,lucky6,now()))
    conn.commit()
    conn.close()

    update_weight(category, table_no, result, prediction, is_manual, lucky6)
    return jsonify({"success":True, "ai":ai_analysis(category,table_no)})

@app.route("/undo-last", methods=["POST"])
def undo_last():
    data = request.json or {}
    category = data.get("category","DG")
    table_no = data.get("table_no","RB01")
    conn = db()
    last = conn.execute("SELECT id FROM game_records WHERE category=? AND table_no=? ORDER BY id DESC LIMIT 1",
                        (category,table_no)).fetchone()
    if last:
        conn.execute("DELETE FROM game_records WHERE id=?", (last["id"],))
        conn.commit()
    conn.close()
    rebuild_weight(category, table_no)
    return jsonify({"success":True, "ai":ai_analysis(category,table_no)})

@app.route("/add-bet", methods=["POST"])
def add_bet():
    data = request.json or {}
    conn = db()
    conn.execute("""INSERT INTO bets(username,category,table_no,bet_side,amount,created_at)
                    VALUES(?,?,?,?,?,?)""",
                 (session.get("user","guest"), data.get("category"), data.get("table_no"),
                  data.get("bet_side"), data.get("amount",0), now()))
    conn.commit(); conn.close()
    return jsonify({"success":True})

if __name__ == "__main__":
    port = int(os.environ.get("PORT","5000"))
    app.run(host="0.0.0.0", port=port)
