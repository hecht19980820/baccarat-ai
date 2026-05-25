
from flask import Flask, render_template, request, jsonify, redirect, session
import sqlite3
from datetime import datetime

app = Flask(__name__)
app.secret_key = "baccarat_secret"

DB = "baccarat.db"

def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS members(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        expire TEXT,
        enabled INTEGER DEFAULT 1
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS records(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        platform TEXT,
        table_no TEXT,
        result TEXT,
        hidden INTEGER DEFAULT 0,
        created_at TEXT
    )
    """)

    cur.execute("SELECT COUNT(*) c FROM members")
    if cur.fetchone()["c"] == 0:
        cur.execute(
            "INSERT INTO members(username,password,expire,enabled) VALUES(?,?,?,?)",
            ("test01","123456","2099-12-31",1)
        )

    conn.commit()
    conn.close()

@app.route("/")
def index():
    if not session.get("member"):
        return redirect("/login")
    return render_template("index.html")

@app.route("/login")
def login():
    return render_template("login.html")

@app.route("/admin")
def admin():
    if not session.get("admin"):
        return redirect("/admin-login")
    return render_template("admin.html")

@app.route("/admin-login")
def admin_login():
    return render_template("admin_login.html")

@app.route("/api/login", methods=["POST"])
def api_login():
    body = request.json

    conn = db()
    row = conn.execute(
        "SELECT * FROM members WHERE username=? AND password=?",
        (body.get("username"), body.get("password"))
    ).fetchone()
    conn.close()

    if not row:
        return jsonify({"ok":False,"msg":"登入失敗"})

    session["member"] = row["username"]

    return jsonify({"ok":True})

@app.route("/api/admin-login", methods=["POST"])
def api_admin_login():
    body = request.json

    if body.get("username") == "admin" and body.get("password") == "Baccarat2026!":
        session["admin"] = True
        return jsonify({"ok":True})

    return jsonify({"ok":False})

@app.route("/api/data")
def api_data():
    conn = db()
    rows = conn.execute(
        "SELECT * FROM records WHERE hidden=0 ORDER BY id ASC"
    ).fetchall()
    conn.close()

    return jsonify({
        "ok":True,
        "records":[dict(r) for r in rows]
    })

@app.route("/api/manual", methods=["POST"])
def api_manual():
    body = request.json

    conn = db()

    conn.execute(
        "INSERT INTO records(platform,table_no,result,created_at) VALUES(?,?,?,?)",
        (
            body.get("platform","DG"),
            body.get("table","RB01"),
            body.get("result","B"),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
    )

    conn.commit()
    conn.close()

    return jsonify({"ok":True})

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
