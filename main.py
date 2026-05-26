
from flask import Flask, render_template, request, jsonify, redirect, session
from datetime import datetime
import sqlite3
import os

app = Flask(__name__)
app.secret_key = "baccarat_secret_2026"

DB = "baccarat.db"

ADMIN_USER = "admin"
ADMIN_PASS = "Baccarat2026!"

def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        table_name TEXT,
        result TEXT,
        is_manual INTEGER DEFAULT 0,
        created_at TEXT
    )
    """)

    conn.commit()
    conn.close()

init_db()

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/admin-login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        user = request.form.get("username")
        password = request.form.get("password")

        if user == ADMIN_USER and password == ADMIN_PASS:
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

    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT * FROM records ORDER BY id DESC LIMIT 100")
    data = c.fetchall()
    conn.close()

    return render_template("admin.html", data=data)

@app.route("/add_record", methods=["POST"])
def add_record():
    data = request.json

    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("""
    INSERT INTO records(table_name,result,is_manual,created_at)
    VALUES(?,?,?,?)
    """, (
        data.get("table"),
        data.get("result"),
        data.get("manual", 0),
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))

    conn.commit()
    conn.close()

    return jsonify({"success": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
