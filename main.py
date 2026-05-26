from flask import Flask, render_template, request, redirect, session, jsonify
from datetime import datetime
import sqlite3, os, json, hashlib

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'baccarat_admin_secret_2026')
DB_PATH = os.environ.get('DB_PATH', 'baccarat_system.db')
ADMIN_USER = os.environ.get('ADMIN_USER', 'admin')
ADMIN_PASS = os.environ.get('ADMIN_PASS', 'Baccarat2026!')
SERIAL_ENABLED = os.environ.get('SERIAL_ENABLED', '0') == '1'
DG_TABLES = ['RB01','RB02','RB03','RB04','RB05','RB06','RB07']
MT_TABLES = ['1','2','3','3A','5','6','7','8','9','10','11','12','13','13A','15']

def now(): return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con=db(); c=con.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, role TEXT DEFAULT "player", agent TEXT DEFAULT "", active INTEGER DEFAULT 1, created_at TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS shoes(id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT, table_no TEXT, result TEXT, cards TEXT, manual INTEGER DEFAULT 0, counted INTEGER DEFAULT 1, created_at TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS stats(provider TEXT, table_no TEXT, banker INTEGER DEFAULT 0, player INTEGER DEFAULT 0, tie INTEGER DEFAULT 0, PRIMARY KEY(provider, table_no))')
    c.execute('CREATE TABLE IF NOT EXISTS serials(id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE, used_by TEXT DEFAULT "", active INTEGER DEFAULT 1, created_at TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT)')
    c.execute('INSERT OR IGNORE INTO users(username,password,role,active,created_at) VALUES(?,?,?,?,?)', ('admin', ADMIN_PASS, 'admin', 1, now()))
    con.commit(); con.close()
init_db()

def login_required(admin=False):
    if not session.get('user'): return False
    if admin and session.get('role')!='admin': return False
    return True

def score_cards(s):
    nums=[]
    for x in (s or '').replace('，', ',').replace('.', ',').replace('-', ',').split(','):
        x=x.strip()
        if x=='': continue
        try: nums.append(int(x)%10)
        except: pass
    if len(nums)<4: return None
    p=sum(nums[:2])%10; b=sum(nums[2:4])%10
    if p>b: return 'P'
    if b>p: return 'B'
    return 'T'

def predict(provider, table_no):
    con=db(); rows=con.execute('SELECT result FROM shoes WHERE provider=? AND table_no=? ORDER BY id DESC LIMIT 60',(provider,table_no)).fetchall(); con.close()
    seq=[r['result'] for r in rows][::-1]
    b=seq.count('B'); p=seq.count('P'); t=seq.count('T')
    last=seq[-1] if seq else ''
    streak=1
    for x in reversed(seq[:-1]):
        if x==last and x in 'BP': streak+=1
        else: break
    if last in 'BP' and streak>=3: pick=last; why=f'連續{streak}手，順勢'
    elif b>p: pick='B'; why='大數據莊偏多'
    elif p>b: pick='P'; why='大數據閒偏多'
    else: pick='B'; why='資料接近，預設保守莊'
    conf=min(88, 52+abs(b-p)*3+min(streak,6)*3)
    return {'pick':pick,'confidence':conf,'why':why,'b':b,'p':p,'t':t,'total':len(seq),'seq':seq[-80:]}

@app.route('/')
def index():
    if not session.get('user'): return redirect('/login')
    return render_template('index.html', dg=DG_TABLES, mt=MT_TABLES, user=session.get('user'), role=session.get('role'))

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        u=request.form.get('username','').strip(); p=request.form.get('password','').strip(); serial=request.form.get('serial','').strip()
        con=db(); row=con.execute('SELECT * FROM users WHERE username=? AND password=? AND active=1',(u,p)).fetchone()
        if not row:
            con.close(); return render_template('login.html', error='帳號或密碼錯誤')
        if SERIAL_ENABLED and row['role']!='admin':
            s=con.execute('SELECT * FROM serials WHERE code=? AND active=1 AND (used_by="" OR used_by=?)',(serial,u)).fetchone()
            if not s: con.close(); return render_template('login.html', error='序號錯誤或已被使用')
            con.execute('UPDATE serials SET used_by=? WHERE code=?',(u,serial)); con.commit()
        con.close(); session['user']=u; session['role']=row['role']; return redirect('/admin' if row['role']=='admin' else '/')
    return render_template('login.html')

@app.route('/logout')
def logout(): session.clear(); return redirect('/login')

@app.route('/admin-login', methods=['GET','POST'])
def admin_login():
    if request.method=='POST':
        if request.form.get('username')==ADMIN_USER and request.form.get('password')==ADMIN_PASS:
            session['user']=ADMIN_USER; session['role']='admin'; return redirect('/admin')
        return render_template('admin_login.html', error='管理員帳密錯誤')
    return render_template('admin_login.html')

@app.route('/admin')
def admin():
    if not login_required(True): return redirect('/admin-login')
    return render_template('admin.html', dg=DG_TABLES, mt=MT_TABLES)

@app.route('/api/state')
def state():
    provider=request.args.get('provider','DG'); table=request.args.get('table','RB01')
    con=db(); rows=con.execute('SELECT * FROM shoes WHERE provider=? AND table_no=? ORDER BY id ASC LIMIT 300',(provider,table)).fetchall(); con.close()
    pred=predict(provider, table)
    return jsonify({'rows':[dict(r) for r in rows], 'prediction':pred})

@app.route('/api/add', methods=['POST'])
def add():
    data=request.json or {}; provider=data.get('provider','DG'); table=data.get('table','RB01')
    result=data.get('result',''); cards=data.get('cards',''); manual=int(data.get('manual',0)); counted=int(data.get('counted',1))
    if cards and result=='AUTO': result=score_cards(cards) or ''
    if result not in ['B','P','T']: return jsonify({'ok':False,'error':'結果錯誤'})
    con=db(); con.execute('INSERT INTO shoes(provider,table_no,result,cards,manual,counted,created_at) VALUES(?,?,?,?,?,?,?)',(provider,table,result,cards,manual,counted,now()))
    if counted:
        col={'B':'banker','P':'player','T':'tie'}[result]
        con.execute('INSERT OR IGNORE INTO stats(provider,table_no) VALUES(?,?)',(provider,table))
        con.execute(f'UPDATE stats SET {col}={col}+1 WHERE provider=? AND table_no=?',(provider,table))
    con.commit(); con.close(); return jsonify({'ok':True})

@app.route('/api/undo', methods=['POST'])
def undo():
    data=request.json or {}; provider=data.get('provider','DG'); table=data.get('table','RB01')
    con=db(); row=con.execute('SELECT * FROM shoes WHERE provider=? AND table_no=? ORDER BY id DESC LIMIT 1',(provider,table)).fetchone()
    if row:
        con.execute('DELETE FROM shoes WHERE id=?',(row['id'],))
        if row['counted']:
            col={'B':'banker','P':'player','T':'tie'}[row['result']]
            con.execute(f'UPDATE stats SET {col}=MAX({col}-1,0) WHERE provider=? AND table_no=?',(provider,table))
    con.commit(); con.close(); return jsonify({'ok':True})

@app.route('/api/clear', methods=['POST'])
def clear():
    data=request.json or {}; provider=data.get('provider','DG'); table=data.get('table','RB01')
    con=db(); con.execute('DELETE FROM shoes WHERE provider=? AND table_no=?',(provider,table)); con.execute('DELETE FROM stats WHERE provider=? AND table_no=?',(provider,table)); con.commit(); con.close(); return jsonify({'ok':True})

@app.route('/api/users', methods=['GET','POST','DELETE'])
def users():
    if not login_required(True): return jsonify({'ok':False}),403
    con=db()
    if request.method=='GET':
        rows=con.execute('SELECT id,username,role,agent,active,created_at FROM users ORDER BY id DESC').fetchall(); con.close(); return jsonify([dict(r) for r in rows])
    data=request.json or {}
    if request.method=='POST':
        con.execute('INSERT OR IGNORE INTO users(username,password,role,agent,active,created_at) VALUES(?,?,?,?,?,?)',(data.get('username'),data.get('password','123456'),data.get('role','player'),data.get('agent',''),1,now())); con.commit(); con.close(); return jsonify({'ok':True})
    uid=data.get('id'); con.execute('DELETE FROM users WHERE id=? AND username<>?',(uid,'admin')); con.commit(); con.close(); return jsonify({'ok':True})

if __name__ == '__main__':
    port=int(os.environ.get('PORT',5000)); app.run(host='0.0.0.0', port=port)
