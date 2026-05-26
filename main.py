
from flask import Flask, render_template, request, jsonify, redirect, session
from datetime import datetime
import os, sqlite3, json, math

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "Baccarat2026_secret")
DB_PATH = os.environ.get("DB_PATH", "baccarat_system.db")

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "Baccarat2026!")

DG_TABLES = ["RB01","RB02","RB03","RB04","RB05","RB06","RB07"]
MT_TABLES = ["1","2","3","3A","5","6","7","8","9","10","11","12","13","13A","15"]

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        role TEXT DEFAULT 'player',
        agent TEXT DEFAULT '',
        expires_at TEXT DEFAULT '2026-12-31 23:59:59'
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS rounds(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        shoe TEXT,
        source TEXT,
        table_no TEXT,
        result TEXT,
        cards TEXT DEFAULT '',
        counted INTEGER DEFAULT 1,
        created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS settings(
        key TEXT PRIMARY KEY,
        value TEXT
    )""")
    c.execute("INSERT OR IGNORE INTO users(username,password,role,expires_at) VALUES(?,?,?,?)",
              (ADMIN_USER, ADMIN_PASS, "admin", "2026-12-31 23:59:59"))
    conn.commit()
    conn.close()

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

@app.before_request
def before():
    init_db()

@app.route("/")
def home():
    if "user" not in session:
        session["user"] = "guest"
        session["role"] = "player"
    return render_template("index.html", dg_tables=DG_TABLES, mt_tables=MT_TABLES)

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        u = request.form.get("username","").strip()
        p = request.form.get("password","").strip()
        conn = db()
        row = conn.execute("SELECT * FROM users WHERE username=? AND password=?", (u,p)).fetchone()
        conn.close()
        if row:
            session["user"] = row["username"]
            session["role"] = row["role"]
            return redirect("/")
        return render_template("login.html", error="帳號或密碼錯誤")
    return render_template("login.html")

@app.route("/admin-login", methods=["GET","POST"])
def admin_login():
    if request.method == "POST":
        u = request.form.get("username","").strip()
        p = request.form.get("password","").strip()
        if u == ADMIN_USER and p == ADMIN_PASS:
            session["user"] = u
            session["role"] = "admin"
            return redirect("/admin")
        return render_template("admin_login.html", error="管理員帳密錯誤")
    return render_template("admin_login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

@app.route("/admin")
def admin():
    if session.get("role") != "admin":
        return redirect("/admin-login")
    return render_template("admin.html", dg_tables=DG_TABLES, mt_tables=MT_TABLES)

@app.route("/api/status")
def api_status():
    source = request.args.get("source","DG")
    table_no = request.args.get("table","RB01")
    conn = db()
    rows = conn.execute("SELECT * FROM rounds WHERE source=? AND table_no=? ORDER BY id ASC", (source, table_no)).fetchall()
    total = len([r for r in rows if r["counted"]])
    b = sum(1 for r in rows if r["result"]=="B" and r["counted"])
    p = sum(1 for r in rows if r["result"]=="P" and r["counted"])
    t = sum(1 for r in rows if r["result"]=="T" and r["counted"])
    last = rows[-1]["result"] if rows else ""
    # simple weighted prediction placeholder
    if total == 0:
        pred, conf = "觀望", 0
    else:
        pred = "莊" if p >= b else "閒"
        conf = min(88, max(25, 50 + abs(b-p)*6))
    conn.close()
    return jsonify({
        "ok": True,
        "source": source, "table": table_no,
        "updated": datetime.now().strftime("%H:%M:%S"),
        "expires": "2026-12-31 23:59:59",
        "stats": {"total": total, "B": b, "P": p, "T": t},
        "prediction": pred, "confidence": conf,
        "rows": [{"id":r["id"],"result":r["result"],"cards":r["cards"],"counted":r["counted"]} for r in rows]
    })

@app.route("/api/add", methods=["POST"])
def api_add():
    data = request.get_json(force=True)
    source = data.get("source","DG")
    table_no = data.get("table","RB01")
    result = data.get("result","")
    cards = data.get("cards","")
    counted = int(data.get("counted",1))
    if result not in ["B","P","T"]:
        return jsonify(ok=False, error="bad result"), 400
    conn = db()
    conn.execute("INSERT INTO rounds(shoe,source,table_no,result,cards,counted,created_at) VALUES(?,?,?,?,?,?,?)",
                 ("default", source, table_no, result, cards, counted, now()))
    conn.commit()
    conn.close()
    return jsonify(ok=True)

@app.route("/api/undo", methods=["POST"])
def api_undo():
    data = request.get_json(force=True)
    source = data.get("source","DG")
    table_no = data.get("table","RB01")
    conn = db()
    row = conn.execute("SELECT id FROM rounds WHERE source=? AND table_no=? ORDER BY id DESC LIMIT 1", (source, table_no)).fetchone()
    if row:
        conn.execute("DELETE FROM rounds WHERE id=?", (row["id"],))
        conn.commit()
    conn.close()
    return jsonify(ok=True)

@app.route("/api/clear", methods=["POST"])
def api_clear():
    data = request.get_json(force=True)
    source = data.get("source","DG")
    table_no = data.get("table","RB01")
    conn = db()
    conn.execute("DELETE FROM rounds WHERE source=? AND table_no=?", (source, table_no))
    conn.commit()
    conn.close()
    return jsonify(ok=True)

@app.route("/api/users", methods=["GET","POST"])
def api_users():
    if session.get("role") != "admin":
        return jsonify(ok=False), 403
    conn = db()
    if request.method == "POST":
        data = request.get_json(force=True)
        conn.execute("INSERT OR REPLACE INTO users(username,password,role,agent,expires_at) VALUES(?,?,?,?,?)",
            (data.get("username"), data.get("password","123456"), data.get("role","player"), data.get("agent",""), data.get("expires_at","2026-12-31 23:59:59")))
        conn.commit()
    rows = conn.execute("SELECT username,role,agent,expires_at FROM users ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify(ok=True, users=[dict(r) for r in rows])

@app.route("/api/user/delete", methods=["POST"])
def api_user_delete():
    if session.get("role") != "admin":
        return jsonify(ok=False), 403
    u = request.get_json(force=True).get("username")
    if u == ADMIN_USER:
        return jsonify(ok=False, error="不能刪除主管理員")
    conn = db()
    conn.execute("DELETE FROM users WHERE username=?", (u,))
    conn.commit()
    conn.close()
    return jsonify(ok=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
