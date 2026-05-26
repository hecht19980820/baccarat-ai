from flask import Flask, render_template, request, jsonify, redirect, session
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = "baccarat_phase2_secret"

DB_NAME = "baccarat_system.db"

DG_TABLES = ["RB01","RB02","RB03","RB04","RB05","RB06","RB07"]
MT_TABLES = ["1","2","3","3A","5","6","7","8","9","10","11","12","13","13A","15"]

ADMIN_USER = "admin"
ADMIN_PASS = "Baccarat2026!"


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
        username TEXT,
        password TEXT,
        expire_date TEXT,
        role TEXT,
        status TEXT,
        agent TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS agents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        password TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS game_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT,
        table_no TEXT,
        result TEXT,
        pattern TEXT,
        is_manual INTEGER,
        prediction TEXT,
        ai_score REAL,
        is_correct INTEGER,
        created_at TEXT
    )
    """)

    conn.commit()
    conn.close()


init_db()


@app.route("/")
def index():
    return render_template(
        "index.html",
        dg_tables=DG_TABLES,
        mt_tables=MT_TABLES
    )


@app.route("/admin-login", methods=["GET", "POST"])
def admin_login():

    if request.method == "POST":

        username = request.form.get("username")
        password = request.form.get("password")

        if username == ADMIN_USER and password == ADMIN_PASS:
            session["admin"] = True
            return redirect("/admin")

    return render_template("admin_login.html")


@app.route("/logout")
def logout():

    session.clear()

    return redirect("/admin-login")


@app.route("/admin")
def admin():

    if not session.get("admin"):
        return redirect("/admin-login")

    conn = db()
    cur = conn.cursor()

    users = cur.execute("""
    SELECT * FROM users
    """).fetchall()

    agents = cur.execute("""
    SELECT * FROM agents
    """).fetchall()

    total_records = cur.execute("""
    SELECT COUNT(*) as c FROM game_records
    """).fetchone()["c"]

    manual_records = cur.execute("""
    SELECT COUNT(*) as c FROM game_records
    WHERE is_manual=1
    """).fetchone()["c"]

    predict_count = cur.execute("""
    SELECT COUNT(*) as c FROM game_records
    WHERE prediction IS NOT NULL
    """).fetchone()["c"]

    correct_count = cur.execute("""
    SELECT COUNT(*) as c FROM game_records
    WHERE is_correct=1
    """).fetchone()["c"]

    hit_rate = 0

    if predict_count > 0:
        hit_rate = round(correct_count / predict_count * 100, 2)

    records = cur.execute("""
    SELECT * FROM game_records
    ORDER BY id DESC
    LIMIT 50
    """).fetchall()

    table_stats = cur.execute("""
    SELECT
        category,
        table_no,
        COUNT(*) as total,
        SUM(CASE WHEN result='莊' THEN 1 ELSE 0 END) as banker,
        SUM(CASE WHEN result='閒' THEN 1 ELSE 0 END) as player,
        SUM(CASE WHEN result='和' THEN 1 ELSE 0 END) as tie_count,
        SUM(CASE WHEN is_correct=1 THEN 1 ELSE 0 END) as corrects,
        COUNT(prediction) as predicts
    FROM game_records
    GROUP BY category, table_no
    """).fetchall()

    conn.close()

    return render_template(
        "admin.html",
        users=users,
        agents=agents,
        total_records=total_records,
        manual_records=manual_records,
        predict_count=predict_count,
        hit_rate=hit_rate,
        records=records,
        table_stats=table_stats
    )


@app.route("/add-user", methods=["POST"])
def add_user():

    conn = db()
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO users
    (
        username,
        password,
        expire_date,
        role,
        status,
        agent
    )
    VALUES (?, ?, ?, ?, ?, ?)
    """, (
        request.form.get("username"),
        request.form.get("password"),
        request.form.get("expire_date"),
        request.form.get("role"),
        request.form.get("status"),
        request.form.get("agent")
    ))

    conn.commit()
    conn.close()

    return redirect("/admin")


@app.route("/delete-user/<int:user_id>")
def delete_user(user_id):

    conn = db()
    cur = conn.cursor()

    cur.execute("""
    DELETE FROM users
    WHERE id=?
    """, (user_id,))

    conn.commit()
    conn.close()

    return redirect("/admin")


@app.route("/add-agent", methods=["POST"])
def add_agent():

    conn = db()
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO agents
    (username,password)
    VALUES (?,?)
    """, (
        request.form.get("username"),
        request.form.get("password")
    ))

    conn.commit()
    conn.close()

    return redirect("/admin")


@app.route("/delete-agent/<int:agent_id>")
def delete_agent(agent_id):

    conn = db()
    cur = conn.cursor()

    cur.execute("""
    DELETE FROM agents
    WHERE id=?
    """, (agent_id,))

    conn.commit()
    conn.close()

    return redirect("/admin")


@app.route("/add-record", methods=["POST"])
def add_record():

    data = request.json

    result = data.get("result")
    pattern = data.get("pattern")
    is_manual = data.get("is_manual", 0)

    category = data.get("category")
    table_no = data.get("table_no")

    prediction = ai_predict(category, table_no)

    ai_score = 50

    is_correct = 0

    if not is_manual:

        if prediction == result:
            is_correct = 1

    conn = db()
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO game_records
    (
        category,
        table_no,
        result,
        pattern,
        is_manual,
        prediction,
        ai_score,
        is_correct,
        created_at
    )
    VALUES (?,?,?,?,?,?,?,?,?)
    """, (
        category,
        table_no,
        result,
        pattern,
        is_manual,
        prediction,
        ai_score,
        is_correct,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))

    conn.commit()
    conn.close()

    return jsonify({
        "success": True
    })


@app.route("/undo-last", methods=["POST"])
def undo_last():

    data = request.json

    category = data.get("category")
    table_no = data.get("table_no")

    conn = db()
    cur = conn.cursor()

    last = cur.execute("""
    SELECT * FROM game_records
    WHERE category=? AND table_no=?
    ORDER BY id DESC
    LIMIT 1
    """, (
        category,
        table_no
    )).fetchone()

    if last:

        cur.execute("""
        DELETE FROM game_records
        WHERE id=?
        """, (last["id"],))

    conn.commit()
    conn.close()

    return jsonify({
        "success": True
    })


def ai_predict(category, table_no):

    conn = db()
    cur = conn.cursor()

    rows = cur.execute("""
    SELECT result
    FROM game_records
    WHERE category=? AND table_no=?
    ORDER BY id DESC
    LIMIT 20
    """, (
        category,
        table_no
    )).fetchall()

    conn.close()

    if len(rows) < 3:
        return "觀察"

    banker = 0
    player = 0
    tie = 0

    for r in rows:

        if r["result"] == "莊":
            banker += 1

        elif r["result"] == "閒":
            player += 1

        elif r["result"] == "和":
            tie += 1

    if banker > player:
        return "莊"

    elif player > banker:
        return "閒"

    return "觀察"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
