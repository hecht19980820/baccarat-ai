
from flask import Flask, render_template, request, jsonify, redirect, session, Response
import sqlite3, os, secrets, string, re, csv, io
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "baccarat_phase4d_secret")
DB = os.environ.get("DB_PATH", "baccarat_system.db")
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "Baccarat2026!")
DG_TABLES = ["RB01","RB02","RB03","RB04","RB05","RB06","RB07"]
MT_TABLES = ["1","2","3","3A","5","6","7","8","9","10","11","12","13","13A","15"]

def now(): return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
def today(): return datetime.now().strftime("%Y-%m-%d")
def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def add_col(cur, table, col, sql):
    cols = [r["name"] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()]
    if col not in cols:
        cur.execute(sql)

def init_db():
    c = conn(); cur = c.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT UNIQUE,password TEXT,expire_date TEXT,role TEXT DEFAULT 'player',status TEXT DEFAULT 'active',agent TEXT DEFAULT '',serial_code TEXT DEFAULT '',created_at TEXT DEFAULT '')""")
    cur.execute("""CREATE TABLE IF NOT EXISTS agents(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT UNIQUE,password TEXT,created_at TEXT DEFAULT '')""")
    cur.execute("""CREATE TABLE IF NOT EXISTS serials(id INTEGER PRIMARY KEY AUTOINCREMENT,code TEXT UNIQUE,days INTEGER DEFAULT 30,role TEXT DEFAULT 'player',agent TEXT DEFAULT '',status TEXT DEFAULT 'unused',used_by TEXT DEFAULT '',used_at TEXT DEFAULT '',created_at TEXT DEFAULT '')""")
    cur.execute("""CREATE TABLE IF NOT EXISTS game_records(id INTEGER PRIMARY KEY AUTOINCREMENT,category TEXT,table_no TEXT,result TEXT,pattern TEXT DEFAULT '',is_manual INTEGER DEFAULT 0,record_type TEXT DEFAULT 'pattern',prediction TEXT DEFAULT '',ai_score REAL DEFAULT 0,is_correct INTEGER DEFAULT NULL,lucky6 INTEGER DEFAULT 0,created_by TEXT DEFAULT '',created_at TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS ai_weights(id INTEGER PRIMARY KEY AUTOINCREMENT,category TEXT,table_no TEXT,banker_weight REAL DEFAULT 1,player_weight REAL DEFAULT 1,tie_weight REAL DEFAULT 1,lucky6_weight REAL DEFAULT 1,trained_count INTEGER DEFAULT 0,updated_at TEXT,UNIQUE(category, table_no))""")
    cur.execute("""CREATE TABLE IF NOT EXISTS bets(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT DEFAULT '',category TEXT,table_no TEXT,bet_side TEXT,amount REAL DEFAULT 0,created_at TEXT)""")
    add_col(cur, "users", "serial_code", "ALTER TABLE users ADD COLUMN serial_code TEXT DEFAULT ''")
    add_col(cur, "game_records", "created_by", "ALTER TABLE game_records ADD COLUMN created_by TEXT DEFAULT ''")
    add_col(cur, "game_records", "record_type", "ALTER TABLE game_records ADD COLUMN record_type TEXT DEFAULT 'pattern'")
    if cur.execute("SELECT COUNT(*) c FROM agents").fetchone()["c"] == 0:
        cur.execute("INSERT INTO agents(username,password,created_at) VALUES(?,?,?)", ("agent001","123456",now()))
    if cur.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] == 0:
        exp = (datetime.now()+timedelta(days=30)).strftime("%Y-%m-%d")
        cur.execute("INSERT INTO users(username,password,expire_date,role,status,agent,serial_code,created_at) VALUES(?,?,?,?,?,?,?,?)", ("player001","123456",exp,"player","active","agent001","",now()))
    for cat, tables in [("DG",DG_TABLES),("MT",MT_TABLES)]:
        for t in tables:
            cur.execute("INSERT OR IGNORE INTO ai_weights(category,table_no,updated_at) VALUES(?,?,?)", (cat,t,now()))
    c.commit(); c.close()
init_db()

def is_admin(): return bool(session.get("admin"))
def is_agent(): return bool(session.get("agent"))
def player_required(): return bool(session.get("user"))

def make_serial():
    chars = string.ascii_uppercase + string.digits
    return "BA-" + "-".join("".join(secrets.choice(chars) for _ in range(4)) for _ in range(4))

def lucky6(pattern):
    s = str(pattern or "").lower()
    return 1 if ("幸運6" in s or "幸运6" in s or "lucky6" in s or "lucky 6" in s or re.search(r"(^|[^0-9])6([^0-9]|$)", s)) else 0

def get_weight(c, cat, table):
    w = c.execute("SELECT * FROM ai_weights WHERE category=? AND table_no=?", (cat,table)).fetchone()
    if not w:
        c.execute("INSERT OR IGNORE INTO ai_weights(category,table_no,updated_at) VALUES(?,?,?)", (cat,table,now()))
        c.commit()
        w = c.execute("SELECT * FROM ai_weights WHERE category=? AND table_no=?", (cat,table)).fetchone()
    return w

def table_records(c, cat, table):
    return c.execute("SELECT * FROM game_records WHERE category=? AND table_no=? ORDER BY id ASC", (cat,table)).fetchall()

def calc_window(rows, n):
    recent = rows[-n:]
    total = max(1, len(recent))
    b = sum(1 for r in recent if r["result"] == "莊")
    p = sum(1 for r in recent if r["result"] == "閒")
    t = sum(1 for r in recent if r["result"] == "和")
    return {"n":n,"total":len(recent),"banker_rate":round(b/total*100,1),"player_rate":round(p/total*100,1),"tie_rate":round(t/total*100,1),"banker":b,"player":p,"tie":t}

def road_pattern(rows):
    pure = [r["result"] for r in rows if r["result"] in ["莊","閒"]]
    if not pure: return {"name":"資料不足","streak":0,"jump":0}
    last = pure[-1]; streak = 1
    for x in reversed(pure[:-1]):
        if x == last: streak += 1
        else: break
    recent = pure[-10:]
    jump = sum(1 for i in range(1,len(recent)) if recent[i] != recent[i-1])
    if streak >= 4: name = f"{last}長龍{streak}"
    elif jump >= 7: name = "近期單跳明顯"
    elif jump >= 5: name = "近期跳路偏多"
    elif streak >= 2: name = f"{last}連{streak}"
    else: name = "路型普通"
    return {"name":name,"streak":streak,"jump":jump}


def shared_model(cat):
    """DG/MT 共享模型：同廳別所有桌資料一起計算，讓越多人用越有參考價值。"""
    c = conn()
    rows = c.execute("SELECT * FROM game_records WHERE category=? ORDER BY id ASC", (cat,)).fetchall()
    c.close()
    if not rows:
        return {"total":0,"banker_rate":0,"player_rate":0,"tie_rate":0,"lucky6_rate":0}
    recent = rows[-300:]
    total = max(1, len(recent))
    b = sum(1 for r in recent if r["result"] == "莊")
    p = sum(1 for r in recent if r["result"] == "閒")
    t = sum(1 for r in recent if r["result"] == "和")
    l = sum(1 for r in recent if r["lucky6"] == 1)
    return {
        "total": len(recent),
        "banker_rate": round(b / total * 100, 1),
        "player_rate": round(p / total * 100, 1),
        "tie_rate": round(t / total * 100, 1),
        "lucky6_rate": round(l / total * 100, 1)
    }


def risk_alerts(rows, ai_data):
    """Phase4-C：AI提醒中心，提示和局、幸運6、過熱、反轉風險。"""
    alerts = []
    recent = rows[-20:]
    pure = [r["result"] for r in recent if r["result"] in ["莊","閒"]]

    if ai_data.get("tie_rate", 0) >= 14:
        alerts.append("和局機率偏高，注意連續追莊閒風險")
    if ai_data.get("lucky6_rate", 0) >= 12:
        alerts.append("幸運6機率上升，可列入觀察")
    if ai_data.get("confidence", 0) < 58:
        alerts.append("AI信心不足，建議觀察或降低注碼")

    if pure:
        last = pure[-1]
        streak = 1
        for x in reversed(pure[:-1]):
            if x == last:
                streak += 1
            else:
                break
        if streak >= 5:
            alerts.append(f"{last}長龍{streak}，注意斷龍反轉")
        elif streak >= 3:
            alerts.append(f"{last}連{streak}，趨勢偏強但避免重壓")

        changes = sum(1 for i in range(1, len(pure[-10:])) if pure[-10:][i] != pure[-10:][i-1])
        if changes >= 7:
            alerts.append("近期單跳明顯，反向波動增加")
        elif changes >= 5:
            alerts.append("近期跳路偏多，避免只看單一路型")

    if not alerts:
        alerts.append("目前無重大風險提醒")
    return alerts

def hit_summary():
    """後台統計：今日、最近100局、最近1000局命中率。"""
    c = conn()
    today_prefix = datetime.now().strftime("%Y-%m-%d")
    today_rows = c.execute("SELECT * FROM game_records WHERE created_at LIKE ? AND prediction IN ('莊','閒','和') AND record_type!='roadfill'", (today_prefix+'%',)).fetchall()
    last100 = c.execute("SELECT * FROM game_records WHERE prediction IN ('莊','閒','和') AND record_type!='roadfill' ORDER BY id DESC LIMIT 100").fetchall()
    last1000 = c.execute("SELECT * FROM game_records WHERE prediction IN ('莊','閒','和') AND record_type!='roadfill' ORDER BY id DESC LIMIT 1000").fetchall()
    c.close()

    def rate(rows):
        if not rows:
            return {"total":0,"correct":0,"rate":0}
        correct = sum(1 for r in rows if r["is_correct"] == 1)
        return {"total":len(rows),"correct":correct,"rate":round(correct/len(rows)*100,1)}

    return {
        "today": rate(today_rows),
        "last100": rate(last100),
        "last1000": rate(last1000)
    }

def ai_analysis(cat, table):
    c = conn(); w = get_weight(c, cat, table); rows = table_records(c, cat, table); c.close()
    windows = [calc_window(rows,n) for n in [10,20,50,100]]
    if not rows:
        return {"suggest":"觀察","confidence":0,"banker_percent":0,"player_percent":0,"trend":"資料不足","reason":"目前資料不足，先觀察。","tie_alert":False,"lucky6_alert":False,"tie_rate":0,"lucky6_rate":0,"windows":windows,"road_pattern":"資料不足","risk":"高"}
    rp = road_pattern(rows[-30:])
    bw,pw,tw,lw = float(w["banker_weight"] or 1),float(w["player_weight"] or 1),float(w["tie_weight"] or 1),float(w["lucky6_weight"] or 1)
    w10,w20,w50,w100 = windows
    shared = shared_model(cat)

    # Phase4-B：桌號模型 + DG/MT共享模型 + 最近局數共同計分
    # 桌號近期 70%，同廳共享 30%；再乘上每桌獨立權重
    table_b = (w10["banker_rate"]*.35+w20["banker_rate"]*.30+w50["banker_rate"]*.25+w100["banker_rate"]*.10)
    table_p = (w10["player_rate"]*.35+w20["player_rate"]*.30+w50["player_rate"]*.25+w100["player_rate"]*.10)
    bs = (table_b * 0.70 + shared["banker_rate"] * 0.30) * bw
    ps = (table_p * 0.70 + shared["player_rate"] * 0.30) * pw
    if "莊" in rp["name"] and rp["streak"] >= 2: bs += min(16, rp["streak"]*4)
    if "閒" in rp["name"] and rp["streak"] >= 2: ps += min(16, rp["streak"]*4)
    if rp["jump"] >= 7:
        pure = [r["result"] for r in rows[-10:] if r["result"] in ["莊","閒"]]
        if pure:
            if pure[-1]=="莊": ps += 6
            else: bs += 6
    total_score = max(1, bs+ps)
    bp,pp = round(bs/total_score*100,1), round(ps/total_score*100,1)
    if bp > pp + 4: sug, conf = "莊", bp
    elif pp > bp + 4: sug, conf = "閒", pp
    else: sug, conf = "觀察", max(bp,pp)
    recent = rows[-50:]
    b = sum(1 for r in recent if r["result"]=="莊"); p = sum(1 for r in recent if r["result"]=="閒"); t = sum(1 for r in recent if r["result"]=="和")
    l = sum(1 for r in recent if r["lucky6"]==1)
    tie_rate = round((w10["tie_rate"]*.45+w20["tie_rate"]*.35+w50["tie_rate"]*.20)*tw,1)
    lucky_rate = round((l/max(1,len(recent))*100)*lw,1)
    risk = "低" if conf>=72 else "中" if conf>=60 else "高"
    shared_note = f"{cat}共享模型：莊{shared['banker_rate']}% / 閒{shared['player_rate']}% / 和{shared['tie_rate']}%，共享資料{shared['total']}局"
    data = {"suggest":sug,"confidence":round(conf,1),"banker_percent":bp,"player_percent":pp,"trend":"近期偏莊" if b>p else "近期偏閒" if p>b else "莊閒接近","reason":f"綜合最近10/20/50/100局、路型、本桌權重與{cat}共享模型；路型：{rp['name']}。{shared_note}。","tie_alert": tie_rate>=14 or sum(1 for r in rows[-10:] if r["result"]=="和")>=2,"lucky6_alert": lucky_rate>=12 or l>=3,"tie_rate":tie_rate,"lucky6_rate":lucky_rate,"windows":windows,"road_pattern":rp["name"],"risk":risk,"shared":shared}
    data["alerts"] = risk_alerts(rows, data)
    return data

def update_weight(cat, table, result, pred, manual, record_type, l6):
    if record_type == "roadfill": return
    c = conn(); w = get_weight(c, cat, table)
    bw,pw,tw,lw = w["banker_weight"],w["player_weight"],w["tie_weight"],w["lucky6_weight"]
    tr = w["trained_count"] or 0
    if result=="莊": bw += .015; pw = max(.7, pw-.004)
    elif result=="閒": pw += .015; bw = max(.7, bw-.004)
    elif result=="和": tw += .025
    if l6: lw += .03
    if pred in ["莊","閒","和"]:
        tr += 1; hit = pred == result
        if pred=="莊": bw += .03 if hit else -.02
        if pred=="閒": pw += .03 if hit else -.02
        if pred=="和": tw += .03 if hit else -.02
    bw,pw,tw,lw = [min(2.3,max(.65,x)) for x in [bw,pw,tw,lw]]
    c.execute("UPDATE ai_weights SET banker_weight=?,player_weight=?,tie_weight=?,lucky6_weight=?,trained_count=?,updated_at=? WHERE category=? AND table_no=?", (bw,pw,tw,lw,tr,now(),cat,table))
    c.commit(); c.close()

def rebuild_weight(cat, table):
    c = conn()
    c.execute("UPDATE ai_weights SET banker_weight=1,player_weight=1,tie_weight=1,lucky6_weight=1,trained_count=0,updated_at=? WHERE category=? AND table_no=?", (now(),cat,table))
    c.commit(); rows = table_records(c, cat, table); c.close()
    for r in rows: update_weight(cat, table, r["result"], r["prediction"], r["is_manual"], r["record_type"], r["lucky6"])

def best_tables(limit=10):
    c = conn()
    rows = c.execute("""SELECT category, table_no, COUNT(*) total,
    SUM(CASE WHEN prediction IN ('莊','閒','和') AND record_type!='roadfill' THEN 1 ELSE 0 END) predicts,
    SUM(CASE WHEN is_correct=1 THEN 1 ELSE 0 END) corrects
    FROM game_records GROUP BY category, table_no ORDER BY total DESC""").fetchall()
    c.close()
    out=[]
    for r in rows:
        predicts, corrects = r["predicts"] or 0, r["corrects"] or 0
        rate = round(corrects/predicts*100,1) if predicts else 0
        ai = ai_analysis(r["category"], r["table_no"])
        score = round(rate*.55 + ai["confidence"]*.45,1) if predicts else round(ai["confidence"]*.45,1)
        out.append({"category":r["category"],"table_no":r["table_no"],"total":r["total"],"predicts":predicts,"hit_rate":rate,"ai_confidence":ai["confidence"],"suggest":ai["suggest"],"score":score})
    return sorted(out, key=lambda x:x["score"], reverse=True)[:limit]

@app.route("/")
def index():
    if not player_required(): return redirect("/login")
    return render_template("index.html", dg_tables=DG_TABLES, mt_tables=MT_TABLES, user=session.get("user"))

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        u,p = request.form.get("username","").strip(), request.form.get("password","").strip()
        c=conn(); row=c.execute("SELECT * FROM users WHERE username=? AND password=?", (u,p)).fetchone(); c.close()
        if row and row["status"]=="active" and (row["expire_date"] or "") >= today():
            session.clear(); session["user"]=row["username"]; session["role"]=row["role"]; session["agent_name"]=row["agent"]; return redirect("/")
        return render_template("login.html", error="帳號密碼錯誤，或會員已到期/停用")
    return render_template("login.html")

@app.route("/activate", methods=["GET","POST"])
def activate():
    if request.method=="POST":
        u,p,code = request.form.get("username","").strip(), request.form.get("password","").strip(), request.form.get("code","").strip().upper()
        c=conn(); s=c.execute("SELECT * FROM serials WHERE code=? AND status='unused'", (code,)).fetchone()
        if not s: c.close(); return render_template("activate.html", error="序號錯誤或已使用")
        if c.execute("SELECT id FROM users WHERE username=?", (u,)).fetchone(): c.close(); return render_template("activate.html", error="帳號已存在")
        exp=(datetime.now()+timedelta(days=int(s["days"] or 30))).strftime("%Y-%m-%d")
        c.execute("INSERT INTO users(username,password,expire_date,role,status,agent,serial_code,created_at) VALUES(?,?,?,?,?,?,?,?)", (u,p,exp,s["role"],"active",s["agent"],code,now()))
        c.execute("UPDATE serials SET status='used',used_by=?,used_at=? WHERE code=?", (u,now(),code))
        c.commit(); c.close(); return redirect("/login")
    return render_template("activate.html")

@app.route("/player-logout")
@app.route("/logout")
def player_logout():
    session.clear(); return redirect("/login")

@app.route("/admin-login", methods=["GET","POST"])
def admin_login():
    if request.method=="POST":
        u,p=request.form.get("username","").strip(), request.form.get("password","").strip()
        if u==ADMIN_USER and p==ADMIN_PASS:
            session.clear(); session["admin"]=True; return redirect("/admin")
        c=conn(); a=c.execute("SELECT * FROM agents WHERE username=? AND password=?", (u,p)).fetchone(); c.close()
        if a:
            session.clear(); session["agent"]=True; session["agent_user"]=a["username"]; return redirect("/admin")
        return render_template("admin_login.html", error="帳號或密碼錯誤")
    return render_template("admin_login.html")

@app.route("/admin-logout")
def admin_logout():
    session.clear(); return redirect("/admin-login")

@app.route("/admin")
def admin():
    if not (is_admin() or is_agent()): return redirect("/admin-login")
    c=conn(); agent=session.get("agent_user") if is_agent() else None
    users=c.execute("SELECT * FROM users WHERE agent=? ORDER BY id DESC", (agent,)).fetchall() if agent else c.execute("SELECT * FROM users ORDER BY id DESC").fetchall()
    serials=c.execute("SELECT * FROM serials WHERE agent=? ORDER BY id DESC LIMIT 100", (agent,)).fetchall() if agent else c.execute("SELECT * FROM serials ORDER BY id DESC LIMIT 100").fetchall()
    agents=c.execute("SELECT * FROM agents ORDER BY id DESC").fetchall() if is_admin() else []
    weights=c.execute("SELECT * FROM ai_weights ORDER BY category, table_no").fetchall()
    records=c.execute("SELECT * FROM game_records ORDER BY id DESC LIMIT 80").fetchall()
    total_records=c.execute("SELECT COUNT(*) c FROM game_records").fetchone()["c"]
    manual_records=c.execute("SELECT COUNT(*) c FROM game_records WHERE is_manual=1").fetchone()["c"]
    roadfill_records=c.execute("SELECT COUNT(*) c FROM game_records WHERE record_type='roadfill'").fetchone()["c"]
    predict_count=c.execute("SELECT COUNT(*) c FROM game_records WHERE prediction IN ('莊','閒','和') AND record_type!='roadfill'").fetchone()["c"]
    correct_count=c.execute("SELECT COUNT(*) c FROM game_records WHERE is_correct=1").fetchone()["c"]
    hit_rate=round(correct_count/predict_count*100,1) if predict_count else 0
    table_stats=c.execute("""SELECT category,table_no,COUNT(*) total,
    SUM(CASE WHEN result='莊' THEN 1 ELSE 0 END) banker,
    SUM(CASE WHEN result='閒' THEN 1 ELSE 0 END) player,
    SUM(CASE WHEN result='和' THEN 1 ELSE 0 END) tie_count,
    SUM(CASE WHEN prediction IN ('莊','閒','和') AND record_type!='roadfill' THEN 1 ELSE 0 END) predicts,
    SUM(CASE WHEN is_correct=1 THEN 1 ELSE 0 END) corrects
    FROM game_records GROUP BY category,table_no ORDER BY category,table_no""").fetchall()
    c.close()
    return render_template("admin.html", users=users, agents=agents, serials=serials, weights=weights, records=records, total_records=total_records, manual_records=manual_records, roadfill_records=roadfill_records, predict_count=predict_count, hit_rate=hit_rate, table_stats=table_stats, best_tables=best_tables(10), hit_summary=hit_summary(), is_super=is_admin(), agent_user=session.get("agent_user"))

@app.route("/add-user", methods=["POST"])
def add_user():
    if not (is_admin() or is_agent()): return redirect("/admin-login")
    agent=request.form.get("agent") if is_admin() else session.get("agent_user")
    c=conn()
    try:
        c.execute("INSERT INTO users(username,password,expire_date,role,status,agent,serial_code,created_at) VALUES(?,?,?,?,?,?,?,?)", (request.form.get("username"),request.form.get("password"),request.form.get("expire_date"),request.form.get("role"),request.form.get("status"),agent,"",now()))
        c.commit()
    except sqlite3.IntegrityError: pass
    c.close(); return redirect("/admin")

@app.route("/delete-user/<int:user_id>")
def delete_user(user_id):
    if not (is_admin() or is_agent()): return redirect("/admin-login")
    c=conn()
    if is_agent(): c.execute("DELETE FROM users WHERE id=? AND agent=?", (user_id,session.get("agent_user")))
    else: c.execute("DELETE FROM users WHERE id=?", (user_id,))
    c.commit(); c.close(); return redirect("/admin")

@app.route("/add-agent", methods=["POST"])
def add_agent():
    if not is_admin(): return redirect("/admin-login")
    c=conn()
    try:
        c.execute("INSERT INTO agents(username,password,created_at) VALUES(?,?,?)", (request.form.get("username"),request.form.get("password"),now()))
        c.commit()
    except sqlite3.IntegrityError: pass
    c.close(); return redirect("/admin")

@app.route("/delete-agent/<int:agent_id>")
def delete_agent(agent_id):
    if not is_admin(): return redirect("/admin-login")
    c=conn(); c.execute("DELETE FROM agents WHERE id=?", (agent_id,)); c.commit(); c.close(); return redirect("/admin")

@app.route("/create-serial", methods=["POST"])
def create_serial():
    if not (is_admin() or is_agent()): return redirect("/admin-login")
    qty, days = int(request.form.get("qty") or 1), int(request.form.get("days") or 30)
    role=request.form.get("role") or "player"; agent=request.form.get("agent") if is_admin() else session.get("agent_user")
    c=conn()
    for _ in range(qty):
        c.execute("INSERT INTO serials(code,days,role,agent,status,created_at) VALUES(?,?,?,?,?,?)", (make_serial(),days,role,agent,"unused",now()))
    c.commit(); c.close(); return redirect("/admin")

@app.route("/api/table")
def api_table():
    if not player_required(): return jsonify({"success":False,"error":"login required"}), 401
    cat,table=request.args.get("category","DG"),request.args.get("table_no","RB01")
    c=conn(); rows=c.execute("SELECT * FROM game_records WHERE category=? AND table_no=? ORDER BY id ASC", (cat,table)).fetchall(); c.close()
    return jsonify({"success":True,"records":[dict(r) for r in rows],"ai":ai_analysis(cat,table)})

@app.route("/add-record", methods=["POST"])
def add_record():
    if not player_required(): return jsonify({"success":False,"error":"login required"}), 401
    d=request.json or {}; cat=d.get("category","DG"); table=d.get("table_no","RB01"); result=d.get("result")
    pattern=d.get("pattern",""); record_type=d.get("record_type","pattern"); manual=1 if d.get("is_manual",0) else 0
    ai=ai_analysis(cat, table)
    if record_type=="roadfill": pred,score,correct="",0,None
    else:
        pred,score=ai["suggest"],ai["confidence"]
        correct=1 if pred in ["莊","閒","和"] and pred==result else 0 if pred in ["莊","閒","和"] else None
    l6=lucky6(pattern)
    c=conn()
    c.execute("INSERT INTO game_records(category,table_no,result,pattern,is_manual,record_type,prediction,ai_score,is_correct,lucky6,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (cat,table,result,pattern,manual,record_type,pred,score,correct,l6,session.get("user"),now()))
    c.commit(); c.close()
    update_weight(cat, table, result, pred, manual, record_type, l6)
    return jsonify({"success":True,"ai":ai_analysis(cat,table)})

@app.route("/undo-last", methods=["POST"])
def undo_last():
    if not player_required(): return jsonify({"success":False,"error":"login required"}), 401
    d=request.json or {}; cat=d.get("category","DG"); table=d.get("table_no","RB01")
    c=conn(); last=c.execute("SELECT id FROM game_records WHERE category=? AND table_no=? ORDER BY id DESC LIMIT 1", (cat,table)).fetchone()
    if last:
        c.execute("DELETE FROM game_records WHERE id=?", (last["id"],)); c.commit()
    c.close(); rebuild_weight(cat, table)
    return jsonify({"success":True,"ai":ai_analysis(cat,table)})

@app.route("/add-bet", methods=["POST"])
def add_bet():
    if not player_required(): return jsonify({"success":False,"error":"login required"}), 401
    d=request.json or {}; c=conn()
    c.execute("INSERT INTO bets(username,category,table_no,bet_side,amount,created_at) VALUES(?,?,?,?,?,?)", (session.get("user"),d.get("category"),d.get("table_no"),d.get("bet_side"),d.get("amount",0),now()))
    c.commit(); c.close(); return jsonify({"success":True})

@app.route("/export-records")
def export_records():
    if not (is_admin() or is_agent()):
        return redirect("/admin-login")
    c = conn()
    rows = c.execute("SELECT * FROM game_records ORDER BY id DESC LIMIT 5000").fetchall()
    c.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID","廳別","桌號","結果","類型","牌型","手動","預測","AI分數","命中","幸運6","建立者","時間"])
    for r in rows:
        writer.writerow([r["id"],r["category"],r["table_no"],r["result"],r["record_type"],r["pattern"],r["is_manual"],r["prediction"],r["ai_score"],r["is_correct"],r["lucky6"],r["created_by"],r["created_at"]])
    return Response(output.getvalue(), mimetype="text/csv; charset=utf-8", headers={"Content-Disposition":"attachment; filename=baccarat_records.csv"})

@app.route("/export-table-stats")
def export_table_stats():
    if not (is_admin() or is_agent()):
        return redirect("/admin-login")
    c = conn()
    rows = c.execute("""SELECT category,table_no,COUNT(*) total,
    SUM(CASE WHEN result='莊' THEN 1 ELSE 0 END) banker,
    SUM(CASE WHEN result='閒' THEN 1 ELSE 0 END) player,
    SUM(CASE WHEN result='和' THEN 1 ELSE 0 END) tie_count,
    SUM(CASE WHEN prediction IN ('莊','閒','和') AND record_type!='roadfill' THEN 1 ELSE 0 END) predicts,
    SUM(CASE WHEN is_correct=1 THEN 1 ELSE 0 END) corrects
    FROM game_records GROUP BY category,table_no ORDER BY category,table_no""").fetchall()
    c.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["廳別","桌號","總局","莊","閒","和","預測次數","命中","勝率"])
    for r in rows:
        predicts = r["predicts"] or 0
        corrects = r["corrects"] or 0
        rate = round(corrects / predicts * 100, 1) if predicts else 0
        writer.writerow([r["category"],r["table_no"],r["total"],r["banker"],r["player"],r["tie_count"],predicts,corrects,str(rate)+"%"])
    return Response(output.getvalue(), mimetype="text/csv; charset=utf-8", headers={"Content-Disposition":"attachment; filename=baccarat_table_stats.csv"})

@app.route("/rebuild-table-ai", methods=["POST"])
def rebuild_table_ai():
    if not (is_admin() or is_agent()):
        return redirect("/admin-login")
    cat = request.form.get("category","DG")
    table = request.form.get("table_no","RB01")
    rebuild_weight(cat, table)
    return redirect("/admin")

@app.route("/clear-roadfill-table", methods=["POST"])
def clear_roadfill_table():
    if not (is_admin() or is_agent()):
        return redirect("/admin-login")
    cat = request.form.get("category","DG")
    table = request.form.get("table_no","RB01")
    c = conn()
    c.execute("DELETE FROM game_records WHERE category=? AND table_no=? AND record_type='roadfill'", (cat, table))
    c.commit()
    c.close()
    rebuild_weight(cat, table)
    return redirect("/admin")

@app.route("/api/data-health")
def api_data_health():
    if not (is_admin() or is_agent()):
        return jsonify({"success":False}), 401
    c = conn()
    total = c.execute("SELECT COUNT(*) c FROM game_records").fetchone()["c"]
    pattern = c.execute("SELECT COUNT(*) c FROM game_records WHERE record_type!='roadfill'").fetchone()["c"]
    roadfill = c.execute("SELECT COUNT(*) c FROM game_records WHERE record_type='roadfill'").fetchone()["c"]
    users = c.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    serials_unused = c.execute("SELECT COUNT(*) c FROM serials WHERE status='unused'").fetchone()["c"]
    c.close()
    return jsonify({"success":True,"total":total,"pattern":pattern,"roadfill":roadfill,"users":users,"serials_unused":serials_unused})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT","5000")))
