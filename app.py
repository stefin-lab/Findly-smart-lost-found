from flask import Flask, request, jsonify, render_template_string, session
import sqlite3, os, base64, uuid
from datetime import datetime
from difflib import SequenceMatcher

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY','findly-demo-secret')
DB='lost_found.db'
UPLOAD='static/uploads'
MAX_IMAGE=2*1024*1024


def db():
    x=sqlite3.connect(DB); x.row_factory=sqlite3.Row; return x

def init_db():
    os.makedirs(UPLOAD,exist_ok=True); x=db()
    x.execute('''CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT UNIQUE,password TEXT,role TEXT,full_name TEXT)''')
    x.execute('''CREATE TABLE IF NOT EXISTS items(id INTEGER PRIMARY KEY AUTOINCREMENT,record_type TEXT,item_name TEXT,category TEXT,colour TEXT,location TEXT,item_date TEXT,description TEXT,contact TEXT,status TEXT DEFAULT 'Active',created_at TEXT DEFAULT CURRENT_TIMESTAMP,image_path TEXT,reporter_name TEXT,item_condition TEXT,identifying_features TEXT,claimed_by TEXT,resolved_at TEXT,owner_username TEXT)''')
    x.execute('''CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,item_id INTEGER,message TEXT,notification_type TEXT DEFAULT 'Match',is_read INTEGER DEFAULT 0,created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    x.execute('''CREATE TABLE IF NOT EXISTS activity(id INTEGER PRIMARY KEY AUTOINCREMENT,item_id INTEGER,action TEXT,details TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    cols={r['name'] for r in x.execute('PRAGMA table_info(items)').fetchall()}
    for n,t in {'image_path':'TEXT','reporter_name':'TEXT','item_condition':'TEXT','identifying_features':'TEXT','claimed_by':'TEXT','resolved_at':'TEXT','owner_username':'TEXT','claim_reason':'TEXT','claim_username':'TEXT'}.items():
        if n not in cols: x.execute(f'ALTER TABLE items ADD COLUMN {n} {t}')
    x.execute("INSERT OR IGNORE INTO users(username,password,role,full_name) VALUES('student','student123','Student','Student User')")
    x.execute("INSERT OR IGNORE INTO users(username,password,role,full_name) VALUES('admin','admin123','Admin','FINDLY Administrator')")
    x.commit(); x.close()
init_db()

def norm(v): return str(v or '').strip().lower()
def sim(a,b):
    a,b=norm(a),norm(b)
    if not a or not b:return 0
    if a==b:return 1
    r=SequenceMatcher(None,a,b).ratio(); A=set(a.split()); B=set(b.split())
    w=len(A&B)/max(len(A),len(B)) if A and B else 0
    if a in b or b in a:r=max(r,.9)
    return max(r,w)

def date_sim(a,b):
    if not a or not b:return 0
    try:d=abs((datetime.strptime(a,'%Y-%m-%d')-datetime.strptime(b,'%Y-%m-%d')).days)
    except:return 0
    return 1 if d==0 else .7 if d==1 else .4 if d<=3 else 0

def score_match(a,b):
    s=0; reasons=[]; n=sim(a['item_name'],b['item_name']); s+=round(n*30)
    if n>=.85:reasons.append('Similar item name')
    elif n>=.55:reasons.append('Partially similar item name')
    if norm(a['category'])==norm(b['category']):s+=20; reasons.append('Same category')
    c1,c2=norm(a['colour']),norm(b['colour'])
    if c1 and c2:
        if c1==c2:s+=15; reasons.append('Same colour')
        elif sim(c1,c2)>=.7:s+=8; reasons.append('Similar colour')
    l1,l2=norm(a['location']),norm(b['location'])
    if l1 and l2:
        if l1==l2:s+=20; reasons.append('Same location')
        elif sim(l1,l2)>=.75:s+=10; reasons.append('Similar location')
    d=date_sim(a['item_date'],b['item_date']); s+=round(d*15)
    if d==1:reasons.append('Same date')
    elif d>=.7:reasons.append('Nearby date')
    elif d>=.4:reasons.append('Date within 3 days')
    return min(s,100),reasons

def matches(item):
    x=db(); opposite='Found Item' if item['record_type']=='Lost Item' else 'Lost Item'
    rows=x.execute("SELECT * FROM items WHERE record_type=? AND status='Active' AND id!=?",(opposite,item.get('id',-1))).fetchall(); x.close(); out=[]
    for r in rows:
        s,reasons=score_match(item,r)
        if s>=40: out.append({**{k:r[k] for k in ['id','item_name','record_type','category','colour','location','item_date','image_path']},'score':s,'reasons':reasons})
    return sorted(out,key=lambda z:z['score'],reverse=True)[:10]

def activity(i,action,details=''):
    x=db(); x.execute('INSERT INTO activity(item_id,action,details) VALUES(?,?,?)',(i,action,details)); x.commit(); x.close()

def image_save(data):
    if not data:return ''
    if not data.startswith('data:image/'):raise ValueError('Invalid image.')
    h,e=data.split(',',1); raw=base64.b64decode(e)
    if len(raw)>MAX_IMAGE:raise ValueError('Image must be 2 MB or smaller.')
    ext='.png' if 'image/png' in h else '.jpg' if 'image/jpeg' in h or 'image/jpg' in h else '.webp' if 'image/webp' in h else None
    if not ext:raise ValueError('Only PNG, JPG and WEBP are supported.')
    name=uuid.uuid4().hex+ext; path=os.path.join(UPLOAD,name); open(path,'wb').write(raw); return '/static/uploads/'+name

def image_delete(p):
    if p and p.startswith('/static/uploads/'):
        try: os.remove(p.lstrip('/').replace('/',os.sep))
        except OSError: pass

def login_required(f):
    from functools import wraps
    @wraps(f)
    def w(*a,**kw):
        if 'username' not in session:return jsonify(success=False,message='Login required'),401
        return f(*a,**kw)
    return w

@app.route('/api/login',methods=['POST'])
def login():
    d=request.get_json() or {}; x=db(); u=x.execute('SELECT * FROM users WHERE lower(username)=? AND password=?',(norm(d.get('username')),str(d.get('password','')))).fetchone(); x.close()
    if not u:return jsonify(success=False,message='Invalid username or password'),401
    session.update(username=u['username'],role=u['role'],full_name=u['full_name']); return jsonify(success=True,username=u['username'],role=u['role'],full_name=u['full_name'])
@app.route('/api/logout',methods=['POST'])
def logout():session.clear();return jsonify(success=True)
@app.route('/api/me')
def me():return jsonify(logged_in='username' in session,username=session.get('username'),role=session.get('role'),full_name=session.get('full_name'))
@app.route('/')
def home():return render_template_string(HTML)

@app.route('/api/items')
@login_required
def items():
    x=db(); r=x.execute('SELECT * FROM items ORDER BY id DESC').fetchall(); x.close(); return jsonify([dict(a) for a in r])
@app.route('/api/items',methods=['POST'])
@login_required
def create():
    d=request.get_json() or {}
    for k in ['record_type','item_name','category','location','item_date']:
        if not str(d.get(k,'')).strip():return jsonify(success=False,message=f'{k} is required'),400
    try:p=image_save(d.get('image_data',''))
    except ValueError as e:return jsonify(success=False,message=str(e)),400
    x=db(); c=x.execute('''INSERT INTO items(record_type,item_name,category,colour,location,item_date,description,contact,status,image_path,reporter_name,item_condition,identifying_features,owner_username) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(d['record_type'],d['item_name'].strip(),d['category'],d.get('colour','').strip(),d['location'],d['item_date'],d.get('description','').strip(),d.get('contact','').strip(),'Active',p,d.get('reporter_name','').strip() or session['full_name'],d.get('item_condition',''),d.get('identifying_features','').strip(),session['username'])); i=c.lastrowid; x.commit(); r=x.execute('SELECT * FROM items WHERE id=?',(i,)).fetchone(); x.close(); item=dict(r); activity(i,'Item reported',f"{item['record_type']} reported by {session['full_name']}"); m=matches(item)
    if m:
        activity(i,'Possible match detected',f"Best match: {m[0]['item_name']} ({m[0]['score']}%)"); x=db(); x.execute('INSERT INTO notifications(item_id,message) VALUES(?,?)',(i,f"Possible match for '{item['item_name']}' — {m[0]['score']}% match.")); x.execute('INSERT INTO notifications(item_id,message) VALUES(?,?)',(m[0]['id'],f"A possible match was found for '{m[0]['item_name']}' — {m[0]['score']}% match.")); x.commit(); x.close()
    return jsonify(success=True,item=item,matches=m)
@app.route('/api/items/<int:i>')
@login_required
def get_item(i):
    x=db(); r=x.execute('SELECT * FROM items WHERE id=?',(i,)).fetchone(); x.close(); return (jsonify(dict(r)),200) if r else (jsonify(message='Item not found'),404)
@app.route('/api/items/<int:i>',methods=['PUT'])
@login_required
def update(i):
    d=request.get_json() or {}; x=db(); old=x.execute('SELECT * FROM items WHERE id=?',(i,)).fetchone()
    if not old:x.close();return jsonify(message='Item not found'),404
    if session['role']!='Admin' and old['owner_username'] and old['owner_username']!=session['username']:x.close();return jsonify(message='You can edit only your own reports.'),403
    p=old['image_path'] or ''
    try:
        if d.get('image_data'):p=image_save(d['image_data'])
    except ValueError as e:x.close();return jsonify(message=str(e)),400
    x.execute('''UPDATE items SET record_type=?,item_name=?,category=?,colour=?,location=?,item_date=?,description=?,contact=?,image_path=?,reporter_name=?,item_condition=?,identifying_features=? WHERE id=?''',(d.get('record_type',old['record_type']),d.get('item_name',old['item_name']),d.get('category',old['category']),d.get('colour',''),d.get('location',old['location']),d.get('item_date',old['item_date']),d.get('description',''),d.get('contact',''),p,d.get('reporter_name',old['reporter_name'] or ''),d.get('item_condition',old['item_condition'] or ''),d.get('identifying_features',old['identifying_features'] or ''),i));x.commit();x.close();image_delete(old['image_path']);activity(i,'Item updated','Report details were updated.');return jsonify(success=True)
@app.route('/api/items/<int:i>',methods=['DELETE'])
@login_required
def delete(i):
    x=db();old=x.execute('SELECT * FROM items WHERE id=?',(i,)).fetchone()
    if not old:x.close();return jsonify(message='Item not found'),404
    if session['role']!='Admin' and old['owner_username'] and old['owner_username']!=session['username']:x.close();return jsonify(message='Only admin can delete another user report.'),403
    x.execute('DELETE FROM items WHERE id=?',(i,));x.execute('DELETE FROM activity WHERE item_id=?',(i,));x.execute('DELETE FROM notifications WHERE item_id=?',(i,));x.commit();x.close();image_delete(old['image_path']);return jsonify(success=True)

@app.route('/api/items/<int:i>/claim',methods=['PUT'])
@login_required
def claim(i):
    d=request.get_json() or {}; reason=str(d.get('reason','')).strip()
    x=db(); r=x.execute('SELECT * FROM items WHERE id=?',(i,)).fetchone()
    if not r: x.close(); return jsonify(message='Item not found'),404
    if r['status']!='Active': x.close(); return jsonify(message='Only active items can receive a claim.'),400
    x.execute("UPDATE items SET status='Claim Requested',claimed_by=?,claim_reason=?,claim_username=? WHERE id=?",(session['full_name'],reason,session['username'],i)); x.commit(); x.close()
    activity(i,'Claim submitted',f"Claim submitted by {session['full_name']}: {reason or 'No reason provided'}")
    return jsonify(success=True,message='Claim request submitted for admin approval.')
@app.route('/api/items/<int:i>/approve-claim',methods=['PUT'])
@login_required
def approve_claim(i):
    if session['role']!='Admin': return jsonify(message='Admin access required'),403
    x=db(); r=x.execute('SELECT * FROM items WHERE id=?',(i,)).fetchone()
    if not r: x.close(); return jsonify(message='Item not found'),404
    if r['status']!='Claim Requested': x.close(); return jsonify(message='No pending claim.'),400
    x.execute("UPDATE items SET status='Claimed',resolved_at=CURRENT_TIMESTAMP WHERE id=?",(i,)); x.commit(); x.close(); activity(i,'Claim approved',f"Admin approved claim for {r['claimed_by'] or 'claimant'}")
    return jsonify(success=True,message='Claim approved.')
@app.route('/api/items/<int:i>/reject-claim',methods=['PUT'])
@login_required
def reject_claim(i):
    if session['role']!='Admin': return jsonify(message='Admin access required'),403
    x=db(); r=x.execute('SELECT * FROM items WHERE id=?',(i,)).fetchone()
    if not r: x.close(); return jsonify(message='Item not found'),404
    x.execute("UPDATE items SET status='Active',claimed_by=NULL,claim_reason=NULL,claim_username=NULL,resolved_at=NULL WHERE id=?",(i,)); x.commit(); x.close(); activity(i,'Claim rejected','Admin rejected the claim request.')
    return jsonify(success=True,message='Claim rejected.')
@app.route('/api/items/<int:i>/return',methods=['PUT'])
@login_required
def returned(i):
    if session['role']!='Admin': return jsonify(message='Admin access required'),403
    d=request.get_json() or {}; name=d.get('receiver','').strip(); x=db(); r=x.execute('SELECT * FROM items WHERE id=?',(i,)).fetchone()
    if not r: x.close(); return jsonify(message='Item not found'),404
    if r['status'] not in ('Claimed','Claim Requested'): x.close(); return jsonify(message='Item must be claimed before return.'),400
    x.execute("UPDATE items SET status='Returned',claimed_by=COALESCE(?,claimed_by),resolved_at=CURRENT_TIMESTAMP WHERE id=?",(name or None,i)); x.commit(); x.close(); activity(i,'Item returned',f"Returned to {name or r['claimed_by'] or 'claimant'}")
    return jsonify(success=True,message='Item marked as returned.')
@app.route('/api/items/<int:i>/activity')
@login_required
def timeline(i):
    x=db();r=x.execute('SELECT * FROM activity WHERE item_id=? ORDER BY id',(i,)).fetchall();x.close();return jsonify([dict(a) for a in r])

@app.route('/api/items/<int:i>/matches')
@login_required
def item_matches(i):
    x=db(); r=x.execute('SELECT * FROM items WHERE id=?',(i,)).fetchone(); x.close()
    if not r: return jsonify(item={},matches=[]),404
    return jsonify(item=dict(r),matches=matches(dict(r)))

@app.route('/api/compare/<int:a>/<int:b>')
@login_required
def compare(a,b):
    x=db(); l=x.execute('SELECT * FROM items WHERE id=?',(a,)).fetchone(); rr=x.execute('SELECT * FROM items WHERE id=?',(b,)).fetchone(); x.close()
    if not l or not rr: return jsonify(message='Item not found'),404
    score,reasons=score_match(dict(l),dict(rr))
    return jsonify(left=dict(l),right=dict(rr),score=score,reasons=reasons)

@app.route('/api/profile')
@login_required
def profile():
    x=db(); u=x.execute('SELECT * FROM users WHERE username=?',(session['username'],)).fetchone()
    lost=x.execute("SELECT COUNT(*) n FROM items WHERE owner_username=? AND record_type='Lost Item'",(session['username'],)).fetchone()['n']
    found=x.execute("SELECT COUNT(*) n FROM items WHERE owner_username=? AND record_type='Found Item'",(session['username'],)).fetchone()['n']
    returned=x.execute("SELECT COUNT(*) n FROM items WHERE owner_username=? AND status='Returned'",(session['username'],)).fetchone()['n']
    claims=x.execute("SELECT COUNT(*) n FROM items WHERE claim_username=? AND status='Claim Requested'",(session['username'],)).fetchone()['n']
    successful=x.execute("SELECT COUNT(*) n FROM items WHERE claim_username=? AND status='Returned'",(session['username'],)).fetchone()['n']
    points=lost*5+found*10+successful*30
    badges=[]
    if found>=1: badges.append('🏅 Good Samaritan')
    if found>=3: badges.append('🤝 Campus Helper')
    if successful>=1: badges.append('🏆 Lost & Found Hero')
    if points>=100: badges.append('🛡️ Campus Guardian')
    x.close()
    return jsonify(full_name=u['full_name'] if u else session['full_name'],username=session['username'],role=session['role'],lost=lost,found=found,returned=returned,active_claims=claims,successful_returns=successful,points=points,badges=badges)

@app.route('/api/claims')
@login_required
def claims():
    if session['role']!='Admin': return jsonify([])
    x=db(); r=x.execute("SELECT * FROM items WHERE status='Claim Requested' ORDER BY id DESC").fetchall(); x.close(); return jsonify([dict(a) for a in r])

@app.route('/api/users')
@login_required
def users_admin():
    if session['role']!='Admin': return jsonify(message='Admin access required'),403
    x=db(); r=x.execute("SELECT u.username,u.full_name,u.role,COUNT(i.id) reports FROM users u LEFT JOIN items i ON i.owner_username=u.username GROUP BY u.username ORDER BY u.id").fetchall(); x.close(); return jsonify([dict(a) for a in r])

@app.route('/api/notifications')
@login_required
def notifications():
    x=db();r=x.execute('SELECT * FROM notifications ORDER BY id DESC LIMIT 30').fetchall();n=x.execute('SELECT COUNT(*) n FROM notifications WHERE is_read=0').fetchone()['n'];x.close();return jsonify(notifications=[dict(a) for a in r],unread=n)
@app.route('/api/notifications/read',methods=['PUT'])
@login_required
def read_notifications():
    x=db();x.execute('UPDATE notifications SET is_read=1');x.commit();x.close();return jsonify(success=True)
@app.route('/api/analytics')
@login_required
def analytics():
    x=db(); q=lambda sql:x.execute(sql).fetchone()['n']; total=q('SELECT COUNT(*) n FROM items'); lost=q("SELECT COUNT(*) n FROM items WHERE record_type='Lost Item'"); found=q("SELECT COUNT(*) n FROM items WHERE record_type='Found Item'"); returned=q("SELECT COUNT(*) n FROM items WHERE status='Returned'"); matched=q("SELECT COUNT(*) n FROM notifications WHERE notification_type='Match'"); cats=x.execute('SELECT category,COUNT(*) count FROM items GROUP BY category ORDER BY count DESC').fetchall(); locs=x.execute('SELECT location,COUNT(*) count FROM items GROUP BY location ORDER BY count DESC LIMIT 10').fetchall(); months=x.execute("SELECT substr(created_at,1,7) month,COUNT(*) count FROM items GROUP BY substr(created_at,1,7) ORDER BY month DESC LIMIT 8").fetchall(); x.close(); return jsonify(total=total,lost=lost,found=found,matched=matched,returned=returned,match_rate=round(matched/total*100,1) if total else 0,return_rate=round(returned/total*100,1) if total else 0,categories=[dict(a) for a in cats],locations=[dict(a) for a in locs],months=[dict(a) for a in months])

HTML=r'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>FINDLY</title><style>
:root{--bg:#f4f7fb;--card:#fff;--text:#172033;--muted:#718096;--border:#e2e8f0;--soft:#f7f9fc;--p:#2f6fed}*{box-sizing:border-box}body{margin:0;font-family:Arial;background:var(--bg);color:var(--text)}body.dark{--bg:#111827;--card:#1f2937;--text:#f3f4f6;--muted:#aab4c5;--border:#374151;--soft:#273449}header{position:sticky;top:0;z-index:20;background:var(--card);border-bottom:1px solid var(--border);padding:14px 5%;display:flex;justify-content:space-between;align-items:center}.logo{font-size:23px;font-weight:800;color:var(--p);display:flex;gap:10px;align-items:center}.logo i{background:var(--p);color:#fff;border-radius:10px;padding:9px;font-style:normal}.container{width:90%;max-width:1400px;margin:25px auto}.card,.stat,.login{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:22px;margin-bottom:18px;box-shadow:0 8px 25px #00000008}.stats{display:grid;grid-template-columns:repeat(6,1fr);gap:12px}.stat small{color:var(--muted)}.stat b{font-size:26px;display:block;margin-top:7px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:15px}.full{grid-column:1/-1}.field{display:flex;flex-direction:column;gap:6px}input,select,textarea{padding:11px;border:1px solid var(--border);border-radius:8px;background:var(--card);color:var(--text)}textarea{min-height:90px}.filters{display:grid;grid-template-columns:2fr 1fr 1fr 1fr;gap:9px}.row{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}button{border:0;border-radius:8px;padding:9px 13px;font-weight:700;cursor:pointer}.primary{background:var(--p);color:white}.secondary{background:var(--soft);color:var(--text);border:1px solid var(--border)}.danger{background:#ffecec;color:#c53030}.success{background:#eaf8f0;color:#26734a}.purple{background:#f0eaff;color:#6941c6}.table{overflow:auto}table{width:100%;border-collapse:collapse;min-width:1100px}th,td{padding:11px;border-bottom:1px solid var(--border);text-align:left;font-size:13px}th{background:var(--soft);color:var(--muted);font-size:11px}.badge,.reason{display:inline-block;padding:5px 8px;border-radius:20px;font-size:10px;font-weight:800}.lost{background:#fff4e5;color:#a85d00}.found{background:#edf8f1;color:#287d48}.active{background:#eaf2ff;color:#2f6fed}.claim-requested{background:#fff7db;color:#9a6700}.claimed{background:#f0eaff;color:#6941c6}.returned{background:#e8f7f0;color:#23734a}.reason{background:#eef4ff;color:#315ea8;margin:4px}.thumb{width:50px;height:50px;object-fit:cover;border-radius:8px;cursor:pointer}.preview{display:none;max-width:180px;max-height:130px;margin-top:7px}.analytics{display:grid;grid-template-columns:1fr 1fr;gap:20px}.bar{margin:10px 0}.bar div:first-child{display:flex;justify-content:space-between;font-size:12px}.track{height:8px;background:var(--soft);border-radius:20px}.fill{height:100%;background:var(--p);border-radius:20px}.map{height:280px;position:relative;background:var(--soft);border:1px solid var(--border);border-radius:14px}.node{position:absolute;background:var(--card);padding:10px;border:1px solid var(--border);border-radius:10px;font-size:12px;font-weight:bold}.n1{left:8%;top:45%}.n2{left:40%;top:15%}.n3{right:8%;top:45%}.n4{left:40%;bottom:12%}.n5{right:25%;bottom:18%}.timeline{padding:8px}.event{border-left:3px solid var(--p);padding:5px 0 12px 15px;margin-left:5px}.event small{color:var(--muted)}.modal,.loginScreen{position:fixed;inset:0;z-index:100;display:flex;align-items:center;justify-content:center;background:#0009;padding:20px}.modal{display:none}.modalBox,.login{width:min(700px,100%);max-height:90vh;overflow:auto}.login{width:min(420px,100%);margin:0}.toast{position:fixed;right:20px;bottom:20px;background:#172b4d;color:white;padding:12px 17px;border-radius:8px;display:none;z-index:200}.hidden{display:none!important}@media(max-width:1100px){.stats{grid-template-columns:repeat(3,1fr)}.filters{grid-template-columns:1fr 1fr}}@media(max-width:700px){.container{width:94%}.grid,.analytics,.filters{grid-template-columns:1fr}.full{grid-column:auto}.stats{grid-template-columns:1fr 1fr}header .sub{display:none}}
.feature-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.feature-card{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:16px;box-shadow:0 8px 25px #00000008}.match-big{font-size:28px;font-weight:900;color:var(--p)}.heat{margin:8px 0}.heatline{height:9px;background:var(--soft);border-radius:20px;overflow:hidden}.heatline i{display:block;height:100%;background:linear-gradient(90deg,#2f6fed,#7c3aed)}.profile{display:grid;grid-template-columns:auto 1fr auto;gap:15px;align-items:center}.avatar{width:60px;height:60px;border-radius:16px;background:var(--p);color:white;display:grid;place-items:center;font-size:25px;font-weight:900}.compare{display:grid;grid-template-columns:1fr auto 1fr;gap:15px}.compare-side{background:var(--soft);padding:15px;border-radius:12px}.vs{display:grid;place-items:center;font-weight:900;color:var(--muted)}.mobile-nav{display:none}@media(max-width:900px){.feature-grid,.analytics,.compare{grid-template-columns:1fr}.vs{display:none}}@media(max-width:700px){.mobile-nav{display:flex;position:fixed;bottom:0;left:0;right:0;background:var(--card);border-top:1px solid var(--border);z-index:30;justify-content:space-around;padding:8px}.mobile-nav button{background:transparent;color:var(--muted)}}
/* ================= DYNAMIC ISLAND ================= */
.dynamic-island{position:fixed;top:14px;left:auto;right:34px;transform:none;width:145px;height:38px;border-radius:24px;background:#050505;color:#fff;z-index:9999;display:flex;align-items:center;justify-content:center;gap:8px;box-shadow:0 10px 30px #0005;cursor:pointer;overflow:hidden;transition:width .45s cubic-bezier(.22,1,.36,1),height .45s cubic-bezier(.22,1,.36,1),border-radius .45s,background .3s}.dynamic-island .di-dot{width:8px;height:8px;border-radius:50%;background:#30d158;box-shadow:0 0 10px #30d158;flex:none}.dynamic-island .di-title{font-size:12px;font-weight:800;letter-spacing:.3px;white-space:nowrap}.dynamic-island .di-icon{font-size:14px;display:none}.dynamic-island.expanded{width:min(390px,calc(100vw - 28px));height:96px;border-radius:28px;justify-content:flex-start;padding:15px 18px;align-items:flex-start}.dynamic-island.expanded .di-icon{display:block}.dynamic-island.expanded .di-content{display:block}.di-content{display:none;min-width:0;flex:1}.di-main{font-size:13px;font-weight:800;margin-bottom:3px}.di-sub{font-size:11px;color:#aab0ba;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.di-score{margin-left:auto;font-size:20px;font-weight:900;color:#5ee68a}.dynamic-island.pulse{animation:diPulse .8s ease}.dynamic-island.match{box-shadow:0 0 0 2px #2f6fed55,0 12px 35px #2f6fed55}.dynamic-island.success{box-shadow:0 0 0 2px #30d15855,0 12px 35px #30d15855}.dynamic-island.warn{box-shadow:0 0 0 2px #ffb34055,0 12px 35px #ffb34055}@keyframes diPulse{0%{transform:scale(1)}45%{transform:scale(1.06)}100%{transform:scale(1)}}@media(max-width:700px){.dynamic-island{top:62px;right:16px;height:34px;width:118px}.dynamic-island.expanded{height:88px}.dynamic-island .di-title{font-size:11px}header{padding-top:52px}}

/* ===== FINDLY PREMIUM iOS GLASS DESIGN ===== */
:root{--glass:rgba(255,255,255,.58);--glass-strong:rgba(255,255,255,.76);--glass-dark:rgba(24,25,29,.62);--glow:rgba(47,111,237,.22);--radius:22px}
body{background:radial-gradient(circle at 12% 8%,rgba(255,255,255,.72),transparent 30%),radial-gradient(circle at 88% 18%,rgba(180,180,180,.18),transparent 32%),linear-gradient(135deg,#e9eaed,#f6f6f4 48%,#e4e5e7);background-attachment:fixed;overflow-x:hidden}
body:before,body:after{content:"";position:fixed;width:280px;height:280px;border-radius:50%;filter:blur(85px);opacity:.24;pointer-events:none;z-index:-1;animation:blob 16s ease-in-out infinite alternate}.dark:before{background:#777b84}.dark:after{background:#3f4248}.dark{background:radial-gradient(circle at 15% 10%,rgba(255,255,255,.07),transparent 30%),radial-gradient(circle at 85% 18%,rgba(120,120,120,.08),transparent 32%),linear-gradient(135deg,#111318,#191b20 52%,#0d0f13)}@keyframes blob{to{transform:translate(70px,45px) scale(1.18)}}
header,.card,.stat,.login,.feature-card,.modalBox,.noti-panel,.search-wrap,.mobile-nav,.bottom-sheet,.glass-panel{background:var(--glass);backdrop-filter:blur(30px) saturate(180%);-webkit-backdrop-filter:blur(30px) saturate(180%);border:1px solid rgba(255,255,255,.68);box-shadow:0 22px 70px rgba(31,41,55,.14),inset 0 1px 0 rgba(255,255,255,.82),inset 0 -1px 0 rgba(255,255,255,.18);border-radius:var(--radius)}
.dark header,.dark .card,.dark .stat,.dark .login,.dark .feature-card,.dark .modalBox,.dark .noti-panel,.dark .search-wrap,.dark .mobile-nav,.dark .bottom-sheet,.dark .glass-panel{background:var(--glass-dark);border-color:rgba(255,255,255,.10);box-shadow:0 18px 55px rgba(0,0,0,.32),inset 0 1px 0 rgba(255,255,255,.08)}
header{margin:10px 2.5%;width:95%;top:10px;border-radius:20px;transition:.3s}.header-title-group{display:flex;align-items:center;justify-content:center;gap:14px;flex:1;min-width:0;margin:0 22px}.header-title-group .sub{white-space:nowrap}.header-title-group #dynamicIsland{margin-left:2px}.dark .header-title-group .sub{color:#f1f1f1}.header-title-group{position:relative}.header-title-group:after{content:"";position:absolute;inset:0;pointer-events:none;background:linear-gradient(90deg,transparent,rgba(255,255,255,.10),transparent);filter:blur(10px);opacity:.35}.card,.stat{transition:transform .3s ease,box-shadow .3s ease}.card:hover,.stat:hover,.feature-card:hover{transform:translateY(-3px);box-shadow:0 22px 60px rgba(31,41,55,.14),inset 0 1px 0 rgba(255,255,255,.75)}
button{transition:transform .18s ease,box-shadow .18s ease,filter .18s ease}button:hover{transform:translateY(-2px);filter:brightness(1.03);box-shadow:0 8px 20px rgba(47,111,237,.15)}button:active{transform:scale(.96)}input,select,textarea{background:rgba(255,255,255,.45)!important;backdrop-filter:blur(12px);border-color:rgba(120,130,160,.25)!important;box-shadow:inset 0 1px 0 rgba(255,255,255,.7)}.dark input,.dark select,.dark textarea{background:rgba(0,0,0,.20)!important;color:var(--text)}
/* spotlight */.search-wrap{position:relative;padding:6px;margin-bottom:12px}.search-wrap input{width:100%;border:0!important;background:transparent!important;font-size:15px;padding:14px 16px}.suggestions{display:none;position:absolute;left:0;right:0;top:62px;z-index:70;padding:10px;border-radius:18px;background:var(--glass-strong);backdrop-filter:blur(25px);box-shadow:0 20px 50px rgba(0,0,0,.15)}.suggestions.show{display:block}.suggestion{padding:10px 12px;border-radius:12px;cursor:pointer}.suggestion:hover{background:rgba(47,111,237,.12)}
/* dynamic island - inline with project title */#dynamicIsland{position:relative;top:auto;left:auto;right:auto;transform:none;width:148px;height:40px;flex:0 0 auto;border-radius:22px;background:linear-gradient(145deg,rgba(35,36,40,.94),rgba(12,13,16,.90));color:#fff;z-index:25;display:inline-flex;align-items:center;justify-content:center;cursor:pointer;box-shadow:0 14px 42px rgba(0,0,0,.32),inset 0 1px 0 rgba(255,255,255,.20),inset 0 -1px 0 rgba(0,0,0,.65);border:1px solid rgba(255,255,255,.18);transition:width .55s cubic-bezier(.22,1,.36,1),height .55s cubic-bezier(.22,1,.36,1),border-radius .45s,box-shadow .4s,transform .25s;overflow:hidden}#dynamicIsland:hover{transform:translateY(-1px);box-shadow:0 18px 50px rgba(0,0,0,.38),inset 0 1px 0 rgba(255,255,255,.22)}.di-compact{display:flex;align-items:center;gap:8px;font-size:12px;font-weight:700}.di-dot{width:7px;height:7px;border-radius:50%;background:#d8d8d8;box-shadow:0 0 10px rgba(255,255,255,.5)}.di-expanded{display:none;width:100%;padding:15px 18px}.expanded{width:min(390px,calc(100vw - 30px))!important;height:142px!important;border-radius:28px!important;box-shadow:0 25px 70px rgba(0,0,0,.45),inset 0 1px 0 rgba(255,255,255,.18)!important}.expanded .di-compact{display:none}.expanded .di-expanded{display:block}.di-top{display:flex;align-items:center;gap:10px}.di-icon{font-size:20px}.di-title{font-size:11px;letter-spacing:.8px;opacity:.65}.di-main{font-size:16px;font-weight:800;margin-top:5px}.di-sub{font-size:11px;opacity:.65;margin-top:4px}.di-score{margin-left:auto;font-size:22px;font-weight:900;color:#e8e8e8}.pulse{animation:diPulse .65s ease}@keyframes diPulse{50%{transform:scale(1.05)}}#dynamicIsland.match{box-shadow:0 0 30px rgba(255,255,255,.16),0 16px 45px rgba(0,0,0,.38)}#dynamicIsland.success{box-shadow:0 0 30px rgba(180,255,210,.18),0 16px 45px rgba(0,0,0,.38)}#dynamicIsland.warn{box-shadow:0 0 30px rgba(255,220,150,.18),0 16px 45px rgba(0,0,0,.38)}
/* sheets / modals */.modal{background:rgba(4,8,18,.42)!important;backdrop-filter:blur(8px)}.bottom-sheet{position:fixed;left:50%;bottom:0;transform:translate(-50%,110%);width:min(620px,100%);z-index:1001;padding:22px 24px 28px;border-radius:28px 28px 0 0;transition:transform .45s cubic-bezier(.22,1,.36,1);display:none}.bottom-sheet.open{display:block;transform:translate(-50%,0)}.grab{width:42px;height:5px;border-radius:9px;background:#aaa;margin:0 auto 18px}.sheet-backdrop{position:fixed;inset:0;background:rgba(0,0,0,.35);backdrop-filter:blur(4px);z-index:1000;display:none}.sheet-backdrop.open{display:block}.sheet-actions{display:flex;gap:10px;margin-top:16px}.sheet-actions button{flex:1}.skeleton{background:linear-gradient(90deg,rgba(255,255,255,.15),rgba(255,255,255,.6),rgba(255,255,255,.15));background-size:200% 100%;animation:shimmer 1.2s infinite;border-radius:12px;height:14px;margin:8px 0}@keyframes shimmer{to{background-position:-200% 0}}
/* match ring */.ring{width:105px;height:105px;border-radius:50%;display:grid;place-items:center;background:conic-gradient(var(--p) var(--score),rgba(120,130,160,.16) 0);position:relative;margin:8px auto}.ring:before{content:"";position:absolute;width:79px;height:79px;border-radius:50%;background:var(--card)}.ring span{position:relative;font-size:23px;font-weight:900}.match-big{font-size:28px;font-weight:900;color:var(--p)}.compare{display:grid;grid-template-columns:1fr 70px 1fr;gap:12px;align-items:center}.compare-side{padding:16px;border-radius:18px;background:rgba(255,255,255,.32);border:1px solid rgba(255,255,255,.45)}.vs{text-align:center;font-weight:900;color:var(--muted)}
/* heatmap */.heat{margin:10px 0}.heat>div:first-child{display:flex;justify-content:space-between;font-size:12px}.heatline{height:10px;background:rgba(120,130,160,.15);border-radius:20px;overflow:hidden;margin-top:5px}.heatline i{display:block;height:100%;background:linear-gradient(90deg,#60a5fa,#8b5cf6);border-radius:20px;transition:width 1s ease}
/* profile */.profile{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:15px}.avatar{width:70px;height:70px;border-radius:50%;display:grid;place-items:center;font-size:28px;font-weight:900;color:white;background:linear-gradient(135deg,#3b82f6,#8b5cf6);box-shadow:0 0 35px rgba(99,102,241,.35)}
/* mobile dock */.mobile-nav{position:fixed;left:50%;bottom:14px;transform:translateX(-50%);width:min(430px,92%);padding:8px;z-index:90;display:none;justify-content:space-around}.mobile-nav button{background:transparent!important;border:0;color:var(--text);box-shadow:none;font-size:11px;min-width:65px}.mobile-nav button:nth-child(2){font-size:12px}.mobile-nav button:nth-child(2)::first-line{font-size:23px}
.section-enter{animation:sectionIn .45s ease}@keyframes sectionIn{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}@media(max-width:700px){header{margin:7px 2%;width:96%}.header-title-group{margin:0 8px;gap:8px}.header-title-group .sub{display:none}.header-title-group #dynamicIsland{width:118px;height:34px;position:relative;top:auto;right:auto}.header-title-group #dynamicIsland.expanded{width:min(390px,calc(100vw - 30px))!important;height:150px!important;position:absolute!important;right:0!important;top:0!important}.mobile-nav{display:flex}.container{padding-bottom:100px}.compare{grid-template-columns:1fr}.vs{order:-1}.profile{grid-template-columns:auto 1fr}.profile>div:last-child{grid-column:1/-1}}
</style></head><body>
<div id="sheetBackdrop" class="sheet-backdrop" onclick="closeSheet()"></div>
<div id="actionSheet" class="bottom-sheet"><div class="grab"></div><h2 id="sheetTitle">FINDLY</h2><p id="sheetText" style="color:var(--muted)"></p><div id="sheetBody"></div><div class="sheet-actions"><button class="secondary" onclick="closeSheet()">Cancel</button><button id="sheetOk" class="primary">Continue</button></div></div>


<div id="loginScreen" class="loginScreen"><div class="login"><div class="logo"><i>✓</i>FINDLY</div><h2>Smart Lost & Found</h2><p style="color:var(--muted)">Sign in to manage campus reports.</p><form id="loginForm"><div class="field"><label>Username</label><input id="lu" required></div><div class="field" style="margin-top:10px"><label>Password</label><input id="lp" type="password" required></div><button class="primary" style="width:100%;margin-top:15px">Sign In</button></form><p style="font-size:12px;color:var(--muted)">Demo: student / student123 &nbsp; | &nbsp; admin / admin123</p></div></div>
<div id="app" class="hidden"><header><div class="logo"><i>✓</i>FINDLY</div><div class="header-title-group"><span class="sub">Smart Lost &amp; Found Management System</span><div id="dynamicIsland" class="dynamic-island" onclick="toggleIsland()"><span class="di-dot"></span><span class="di-title" id="diTitle">FINDLY</span><span class="di-icon" id="diIcon">✦</span><div class="di-content"><div class="di-main" id="diMain">Smart Lost &amp; Found</div><div class="di-sub" id="diSub">Ready to help you find an item</div></div><span class="di-score" id="diScore"></span></div></div><div class="row" style="margin:0"><b id="user"></b><button class="secondary" onclick="toggleNoti()">🔔 <span id="nc">0</span></button><button class="secondary" onclick="dark()">🌙</button><button class="danger" onclick="logout()">Logout</button></div></header><div id="noti" class="card" style="display:none;position:fixed;right:20px;top:70px;width:min(400px,90%);z-index:50"><b>Notifications</b><button class="secondary" style="float:right" onclick="readNoti()">Mark read</button><div id="nl" style="clear:both;padding-top:10px"></div></div>
<div class="container"><div style="display:flex;justify-content:space-between;align-items:end;gap:10px"><div><h1>Smart Lost & Found</h1><p style="color:var(--muted)">Report, search, match, claim and return campus items.</p></div><b id="role"></b></div>
<div class="stats"><div class="stat"><small>Total Items</small><b id="st">0</b></div><div class="stat"><small>Lost Items</small><b id="sl">0</b></div><div class="stat"><small>Found Items</small><b id="sf">0</b></div><div class="stat"><small>Matched</small><b id="sm">0</b></div><div class="stat"><small>Returned</small><b id="sr">0</b></div><div class="stat"><small>Match Rate</small><b id="srate">0%</b></div></div>
<div class="card"><h2 id="ft">Report Lost / Found Item</h2><p style="color:var(--muted)">Complete details improve matching accuracy.</p><form id="form"><div class="grid"><div class="field"><label>Record Type *</label><select id="type"><option>Lost Item</option><option>Found Item</option></select></div><div class="field"><label>Item Name *</label><input id="name" required placeholder="Black Wallet"></div><div class="field"><label>Category *</label><select id="cat" required><option value="">Select</option><option>Wallet</option><option>Mobile Phone</option><option>Laptop</option><option>Bag</option><option>ID Card</option><option>Keys</option><option>Book</option><option>Earphones</option><option>Watch</option><option>Water Bottle</option><option>Umbrella</option><option>Other</option></select></div><div class="field"><label>Colour</label><input id="colour"></div><div class="field"><label>College Location *</label><select id="loc" required><option value="">Select</option><option>College Canteen</option><option>Library</option><option>Computer Lab</option><option>Classroom</option><option>Seminar Hall</option><option>Auditorium</option><option>Parking Area</option><option>Hostel</option><option>Bus / Transport</option><option>Sports Ground</option><option>Administrative Block</option><option>Department Block</option><option>Other</option></select></div><div class="field"><label>Date *</label><input id="date" type="date" required></div><div class="field"><label>Condition</label><select id="condition"><option value="">Select</option><option>New</option><option>Good</option><option>Used</option><option>Damaged</option><option>Unknown</option></select></div><div class="field"><label>Reporter Name</label><input id="reporter"></div><div class="field full"><label>Identifying Features</label><input id="features" placeholder="Sticker, initials, scratch, cover..."></div><div class="field full"><label>Description</label><textarea id="desc"></textarea></div><div class="field"><label>Contact</label><input id="contact"></div><div class="field"><label>Photo</label><input id="image" type="file" accept="image/png,image/jpeg,image/webp" onchange="preview()"><img id="prev" class="preview"></div></div><div class="row"><button class="primary" id="save">Save Item</button><button type="button" class="secondary" onclick="resetForm()">Clear</button></div></form><div id="matches" class="card" style="display:none;background:var(--soft)"><b>🎯 Possible Matching Items</b><div id="matchList"></div></div></div>
<div class="card"><h2>🔍 Advanced Search & Filters</h2><div class="filters"><div class="search-wrap"><input id="search" autocomplete="off" placeholder="⌕  Search FINDLY — items, locations, categories..." oninput="display();suggestSearch()"><div id="suggestions" class="suggestions"></div></div><select id="ftype" onchange="display()"><option value="">All Types</option><option>Lost Item</option><option>Found Item</option></select><select id="fcat" onchange="display()"><option value="">All Categories</option><option>Wallet</option><option>Mobile Phone</option><option>Laptop</option><option>Bag</option><option>ID Card</option><option>Keys</option><option>Book</option><option>Earphones</option><option>Watch</option><option>Other</option></select><select id="floc" onchange="display()"><option value="">All Locations</option><option>College Canteen</option><option>Library</option><option>Computer Lab</option><option>Classroom</option><option>Seminar Hall</option><option>Auditorium</option><option>Parking Area</option><option>Hostel</option><option>Bus / Transport</option><option>Sports Ground</option><option>Administrative Block</option><option>Department Block</option><option>Other</option></select></div><div class="row"><select id="fstatus" onchange="display()"><option value="">All Status</option><option>Active</option><option>Claimed</option><option>Returned</option></select><input id="fdate" type="date" onchange="display"><select id="sort" onchange="display()"><option value="new">Newest First</option><option value="old">Oldest First</option></select><button class="secondary" onclick="clearFilters()">Clear Filters</button></div></div>
<div class="card"><h2>📋 Item Records</h2><div class="table"><table><thead><tr><th>Photo</th><th>ID</th><th>Type</th><th>Item</th><th>Category</th><th>Colour</th><th>Location</th><th>Date</th><th>Status</th><th>Actions</th></tr></thead><tbody id="table"></tbody></table></div></div>
<div class="feature-grid"><div class="feature-card"><h3>⚡ Quick Actions</h3><div class="row"><button class="primary" onclick="document.getElementById('form').scrollIntoView({behavior:'smooth'})">＋ Report</button><button class="secondary" onclick="document.getElementById('search').focus();document.getElementById('search').scrollIntoView({behavior:'smooth'})">🔎 Search</button></div></div><div class="feature-card"><h3>🕒 Recent Activity</h3><div id="recentActivity" style="color:var(--muted)">Loading...</div></div><div class="feature-card"><h3>👤 My Profile</h3><div id="profileMini" style="color:var(--muted)">Loading...</div><button class="secondary" onclick="openProfile()">View Profile</button></div></div>
<div class="card"><h2>🎯 Match History & Explainable Matching</h2><p style="color:var(--muted)">Every score includes the reasons behind the decision.</p><div id="smartMatches" class="feature-grid"></div></div>
<div class="card"><h2>🗺️ Interactive Campus + Location Heatmap</h2><div class="map"><div class="node n1" onclick="filterLocation('Library')">📚 Library</div><div class="node n2" onclick="filterLocation('Department Block')">🏫 Department Block</div><div class="node n3" onclick="filterLocation('College Canteen')">🍴 Canteen</div><div class="node n4" onclick="filterLocation('Computer Lab')">💻 Computer Lab</div><div class="node n5" onclick="filterLocation('Sports Ground')">🏟️ Ground</div></div><div id="heatmap"></div></div>
<div class="card" id="claimCenter"><h2>📋 Claim Approval Center</h2><div id="claimList" style="color:var(--muted)">Loading...</div></div>
<div class="card"><h2>🤖 Explainable Smart-Matching Pipeline</h2><div class="feature-grid"><div class="feature-card">1️⃣ <b>Input</b><p>Item name, category, colour, location and date.</p></div><div class="feature-card">2️⃣ <b>Feature Comparison</b><p>Similarity is calculated for each attribute.</p></div><div class="feature-card">3️⃣ <b>Weighted Score</b><p>Name 30% · Category 20% · Colour 15% · Location 20% · Date 15%.</p></div></div></div>
<div class="card"><h2>📊 Dashboard Analytics</h2><div class="analytics"><div><h3>Items by Category</h3><div id="cats"></div></div><div><h3>Items by Location</h3><div id="locs"></div></div></div></div>
<div class="card"><h2>🗺️ Campus Location View</h2><div class="map"><div class="node n1">📚 Library</div><div class="node n2">🏫 Department Block</div><div class="node n3">🍴 Canteen</div><div class="node n4">💻 Computer Lab</div><div class="node n5">🏟️ Sports Ground</div></div></div>
<div class="card" id="userManagement"><h2>👥 User Management</h2><div id="usersAdmin">Admin-only user overview.</div></div>
<div class="card"><h2>🕒 Activity Timeline</h2><div id="timeline" style="color:var(--muted)">Click Timeline on an item.</div></div></div></div>
<nav class="mobile-nav"><button onclick="scrollTo(0,0)">🏠<br>Home</button><button onclick="document.getElementById('form').scrollIntoView({behavior:'smooth'})">＋<br>Report</button><button onclick="document.getElementById('search').focus();document.getElementById('search').scrollIntoView({behavior:'smooth'})">🔎<br>Search</button><button onclick="openProfile()">👤<br>Profile</button></nav><div id="modal" class="modal"><div class="modalBox card"><button class="secondary" style="float:right" onclick="closeModal()">Close</button><div id="modalContent"></div></div></div><div id="toast" class="toast"></div>
<script>
let items=[],editId=null,user=null;
/* ================= DYNAMIC ISLAND ENGINE ================= */
let diTimer=null;
function island(type='normal',title='FINDLY',main='Smart Lost & Found',sub='Ready to help you find an item',score=''){
 const el=$('dynamicIsland'); if(!el)return;
 $('diTitle').innerText=title; $('diMain').innerText=main; $('diSub').innerText=sub; $('diScore').innerText=score;
 $('diIcon').innerText=type==='match'?'🎯':type==='success'?'✓':type==='warn'?'🔔':'✦';
 el.classList.remove('match','success','warn','pulse'); if(type!=='normal')el.classList.add(type); void el.offsetWidth; el.classList.add('pulse');
 clearTimeout(diTimer); el.classList.add('expanded'); diTimer=setTimeout(()=>el.classList.remove('expanded'),4500);
}
function toggleIsland(){const el=$('dynamicIsland');if(!el)return;el.classList.toggle('expanded');clearTimeout(diTimer);if(el.classList.contains('expanded'))diTimer=setTimeout(()=>el.classList.remove('expanded'),5000)}
const $=id=>document.getElementById(id);function esc(v){return String(v??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#039;')}function toast(s){$('toast').innerText=s;$('toast').style.display='block';setTimeout(()=>$('toast').style.display='none',2500)}
async function session(){let r=await fetch('/api/me'),d=await r.json();if(!d.logged_in){$('loginScreen').classList.remove('hidden');$('app').classList.add('hidden');return}user=d;$('loginScreen').classList.add('hidden');$('app').classList.remove('hidden');$('user').innerText=d.full_name;$('role').innerText='Role: '+d.role;await load();await analytics();await noti();await loadClaims();await smartDashboard();await loadUsers()}
$('loginForm').onsubmit=async e=>{e.preventDefault();let r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:$('lu').value,password:$('lp').value})});let d=await r.json();if(!r.ok)return toast(d.message);toast('Login successful');island('success','WELCOME', 'Welcome back, '+$('lu').value, 'FINDLY is ready for you');session()};async function logout(){await fetch('/api/logout',{method:'POST'});location.reload()}
async function load(){let r=await fetch('/api/items');if(r.status==401)return location.reload();items=await r.json();display();stats();smartDashboard()}
async function display(){let s=$('search').value.toLowerCase(),ty=$('ftype').value,ca=$('fcat').value,lo=$('floc').value,st=$('fstatus').value,dt=$('fdate').value,so=$('sort').value;let a=items.filter(x=>[x.item_name,x.category,x.location,x.record_type,x.colour,x.description,x.identifying_features,x.reporter_name].join(' ').toLowerCase().includes(s)&&(!ty||x.record_type==ty)&&(!ca||x.category==ca)&&(!lo||x.location==lo)&&(!st||x.status==st)&&(!dt||x.item_date==dt));if(so=='new')a.sort((x,y)=>new Date(y.item_date)-new Date(x.item_date));else if(so=='old')a.sort((x,y)=>new Date(x.item_date)-new Date(y.item_date));if(!a.length){$('table').innerHTML='<tr><td colspan="10" style="text-align:center;padding:35px">No records found.</td></tr>';return}$('table').innerHTML=a.map(x=>{let tc=x.record_type=='Lost Item'?'lost':'found',sc=x.status.toLowerCase().replaceAll(' ','-'),can=user.role=='Admin'||x.owner_username==user.username;return `<tr><td>${x.image_path?`<img class="thumb" src="${esc(x.image_path)}" onclick="img('${esc(x.image_path)}')">`:'—'}</td><td>${x.id}</td><td><span class="badge ${tc}">${esc(x.record_type)}</span></td><td><b>${esc(x.item_name)}</b></td><td>${esc(x.category)}</td><td>${esc(x.colour||'-')}</td><td>${esc(x.location)}</td><td>${esc(x.item_date)}</td><td><span class="badge ${sc}">${esc(x.status)}</span></td><td><div class="row"><button class="secondary" onclick="view(${x.id})">View</button><button class="secondary" onclick="timeline(${x.id})">Timeline</button><button class="purple" onclick="matchHistory(${x.id})">Matches</button>${can?`<button class="primary" onclick="edit(${x.id})">Edit</button><button class="danger" onclick="del(${x.id})">Delete</button>`:''}${x.status=='Active'?`<button class="purple" onclick="claim(${x.id})">Claim</button>`:''}${user.role=='Admin'&&x.status=='Claim Requested'?`<button class="success" onclick="approve(${x.id})">Approve</button><button class="danger" onclick="reject(${x.id})">Reject</button>`:''}${user.role=='Admin'&&x.status=='Claimed'?`<button class="success" onclick="ret(${x.id})">Returned</button>`:''}</div></td></tr>`}).join('')}
function stats(){$('st').innerText=items.length;$('sl').innerText=items.filter(x=>x.record_type=='Lost Item').length;$('sf').innerText=items.filter(x=>x.record_type=='Found Item').length;$('sr').innerText=items.filter(x=>x.status=='Returned').length}async function analytics(){let r=await fetch('/api/analytics');if(!r.ok)return;let d=await r.json();$('sm').innerText=d.matched;$('srate').innerText=d.match_rate+'%';bars('cats',d.categories,'category');bars('locs',d.locations,'location');let hm=Math.max(...d.locations.map(x=>x.count),1);$('heatmap').innerHTML='<h3>📍 Location Heatmap</h3>'+d.locations.map(x=>`<div class="heat"><div><span>${esc(x.location)}</span> <b>${x.count}</b></div><div class="heatline"><i style="width:${x.count/hm*100}%"></i></div></div>`).join('')}function bars(id,a,k){let m=Math.max(...a.map(x=>x.count),1);$(id).innerHTML=a.length?a.map(x=>`<div class="bar"><div><span>${esc(x[k])}</span><b>${x.count}</b></div><div class="track"><div class="fill" style="width:${x.count/m*100}%"></div></div></div>`).join(''):'<p>No data yet.</p>'}
function data(){return {record_type:$('type').value,item_name:$('name').value.trim(),category:$('cat').value,colour:$('colour').value.trim(),location:$('loc').value,item_date:$('date').value,item_condition:$('condition').value,reporter_name:$('reporter').value.trim(),identifying_features:$('features').value.trim(),description:$('desc').value.trim(),contact:$('contact').value.trim()}}function fileData(f){if(!f)return Promise.resolve('');if(f.size>2097152)return Promise.reject(new Error('Image must be 2 MB or smaller.'));return new Promise((res,rej)=>{let r=new FileReader();r.onload=()=>res(r.result);r.onerror=rej;r.readAsDataURL(f)})}function preview(){let f=$('image').files[0];if(!f){$('prev').style.display='none';return}if(f.size>2097152){toast('Image must be 2 MB or smaller.');$('image').value='';return}$('prev').src=URL.createObjectURL(f);$('prev').style.display='block'}
$('form').onsubmit=async e=>{e.preventDefault();try{let d=data();d.image_data=await fileData($('image').files[0]);let r=await fetch(editId?'/api/items/'+editId:'/api/items',{method:editId?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)}),z=await r.json();if(!r.ok)throw Error(z.message);if(z.matches?.length){showMatches(z.matches);island('match','NEW MATCH', z.matches[0].item_name, 'Possible match detected', z.matches[0].score+'%');}else{island('success',editId?'UPDATED':'REPORT SAVED', editId?'Item updated successfully':'Your report was added', 'FINDLY is checking for possible matches');}toast(editId?'Item updated.':'Item saved.');editId=null;resetForm(false);await load();await analytics()}catch(e){toast(e.message)}}
function showMatches(a){$('matches').style.display='block';$('matchList').innerHTML=a.map(m=>`<div class="card"><b>${esc(m.item_name)}</b> — ${esc(m.record_type)}<div class="match-score" style="font-weight:900;color:var(--p);margin-top:5px">Match Score: ${m.score}%</div>${(m.reasons||[]).map(r=>`<span class="reason">✓ ${esc(r)}</span>`).join('')}</div>`).join('')}
async function view(i){let r=await fetch('/api/items/'+i),x=await r.json();$('modalContent').innerHTML=`<h2>${esc(x.item_name)}</h2>${x.image_path?`<img src="${esc(x.image_path)}" style="max-width:100%;max-height:300px">`:''}<p><b>Type:</b> ${esc(x.record_type)}</p><p><b>Category:</b> ${esc(x.category)}</p><p><b>Colour:</b> ${esc(x.colour||'-')}</p><p><b>Location:</b> ${esc(x.location)}</p><p><b>Date:</b> ${esc(x.item_date)}</p><p><b>Description:</b> ${esc(x.description||'-')}</p><p><b>Contact:</b> ${esc(x.contact||'-')}</p><p><b>Status:</b> ${esc(x.status)}</p><p><b>Claimed By:</b> ${esc(x.claimed_by||'-')}</p>`;$('modal').style.display='flex'}function img(s){$('modalContent').innerHTML=`<img src="${esc(s)}" style="max-width:100%;max-height:75vh">`;$('modal').style.display='flex'}function closeModal(){$('modal').style.display='none'}
async function edit(i){let r=await fetch('/api/items/'+i),x=await r.json();editId=i;$('type').value=x.record_type;$('name').value=x.item_name;$('cat').value=x.category;$('colour').value=x.colour||'';$('loc').value=x.location;$('date').value=x.item_date;$('condition').value=x.item_condition||'';$('reporter').value=x.reporter_name||'';$('features').value=x.identifying_features||'';$('desc').value=x.description||'';$('contact').value=x.contact||'';$('ft').innerText='Edit Lost / Found Item';$('save').innerText='Update Item';scrollTo({top:0,behavior:'smooth'})}
async function del(i){smartConfirm('Delete item?','Are you sure you want to delete this report?',async()=>{let r=await fetch('/api/items/'+i,{method:'DELETE'}),z=await r.json();toast(z.message||'Item deleted');await load();await analytics()})}async function claim(i){let reason=prompt('Why do you believe this item belongs to you?');if(reason===null)return;let r=await fetch('/api/items/'+i+'/claim',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({reason})}),z=await r.json();toast(z.message);await load();await analytics();timeline(i)}
async function approve(i){let r=await fetch('/api/items/'+i+'/approve-claim',{method:'PUT'}),z=await r.json();toast(z.message);await load();await loadClaims();timeline(i)}
async function reject(i){smartConfirm('Reject claim?','This claim will be returned to Active status.',async()=>{let r=await fetch('/api/items/'+i+'/reject-claim',{method:'PUT'}),z=await r.json();toast(z.message);await load();await loadClaims();timeline(i)})}
async function loadClaims(){if(!user||user.role!='Admin'){document.getElementById('claimCenter').style.display='none';return}let r=await fetch('/api/claims');let a=await r.json();$('claimList').innerHTML=a.length?a.map(x=>`<div class="feature-card"><b>${esc(x.item_name)}</b> — ${esc(x.claimed_by||'Student')}<p>${esc(x.claim_reason||'No reason provided.')}</p><button class="success" onclick="approve(${x.id})">Approve</button> <button class="danger" onclick="reject(${x.id})">Reject</button></div>`).join(''):'No pending claim requests.'}
async function matchHistory(i){let r=await fetch('/api/items/'+i+'/matches'),d=await r.json();$('modalContent').innerHTML='<h2>🎯 Match History — '+esc(d.item.item_name)+'</h2>'+(d.matches.length?d.matches.map(m=>`<div class="feature-card"><div style="display:flex;justify-content:space-between"><b>${esc(m.item_name)}</b><span class="match-big">${m.score}%</span></div><div>${(m.reasons||[]).map(q=>`<span class="reason">✓ ${esc(q)}</span>`).join('')}</div><button class="primary" onclick="compareItems(${i},${m.id})">🆚 Compare</button></div>`).join(''):'<p>No possible matches found.</p>');$('modal').style.display='flex'}
async function compareItems(a,b){let r=await fetch('/api/compare/'+a+'/'+b),d=await r.json();if(!r.ok)return toast(d.message);let side=x=>`<div class="compare-side">${x.image_path?`<img src="${esc(x.image_path)}" style="width:100%;height:180px;object-fit:cover;border-radius:10px">`:''}<h3>${esc(x.item_name)}</h3><p>${esc(x.category)} · ${esc(x.colour||'-')}</p><p>📍 ${esc(x.location)}<br>📅 ${esc(x.item_date)}</p><p>${esc(x.description||'-')}</p></div>`;$('modalContent').innerHTML=`<h2>🆚 Item Comparison</h2><div class="compare">${side(d.left)}<div class="vs">VS<br><span class="match-big">${d.score}%</span></div>${side(d.right)}</div><div style="text-align:center;margin-top:15px">${d.reasons.map(q=>`<span class="reason">✓ ${esc(q)}</span>`).join('')}<p style="color:var(--muted)">Why this is a match? The weighted rule engine found similarities across the reports.</p></div>`;$('modal').style.display='flex'}
async function openProfile(){let r=await fetch('/api/profile'),d=await r.json();$('modalContent').innerHTML=`<div class="profile"><div class="avatar">${esc(d.full_name[0])}</div><div><h2>${esc(d.full_name)}</h2><p>${esc(d.username)} · ${esc(d.role)}</p></div><div><b style="font-size:28px;color:var(--p)">${d.points}</b><br>Points</div></div><div class="feature-grid" style="margin-top:15px"><div class="feature-card">Lost<br><b>${d.lost}</b></div><div class="feature-card">Found<br><b>${d.found}</b></div><div class="feature-card">Returned<br><b>${d.returned}</b></div><div class="feature-card">Active Claims<br><b>${d.active_claims}</b></div></div><h3>🏆 Badges</h3><p>${d.badges.length?d.badges.join(' · '):'No badges yet'}</p>`;$('modal').style.display='flex'}
function filterLocation(v){$('floc').value=v;display();document.getElementById('search').scrollIntoView({behavior:'smooth'});toast('Filtered to '+v)}
async function ret(i){let n=prompt('Enter receiver name:');if(n===null)return;let r=await fetch('/api/items/'+i+'/return',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({receiver:n})}),z=await r.json();toast(z.message);island('success','ITEM RETURNED', 'Return recorded successfully', 'The item has been marked as Returned');await load();await analytics();timeline(i)}
async function timeline(i){let r=await fetch('/api/items/'+i+'/activity'),a=await r.json();$('timeline').innerHTML=a.length?a.map(x=>`<div class="event"><b>${esc(x.action)}</b><div>${esc(x.details||'')}</div><small>${esc(x.created_at)}</small></div>`).join(''):'No activity yet';$('timeline').scrollIntoView({behavior:'smooth'})}
async function smartDashboard(){let out=[];for(const x of items.slice(0,8)){try{let r=await fetch('/api/items/'+x.id+'/matches');let d=await r.json();if(d.matches&&d.matches[0])out.push({x,m:d.matches[0]})}catch(e){}}$('smartMatches').innerHTML=out.slice(0,6).map(o=>`<div class="feature-card"><span class="badge ${o.x.record_type=='Lost Item'?'lost':'found'}">${esc(o.x.record_type)}</span><h3>${esc(o.x.item_name)}</h3><div class="match-big">${o.m.score}% MATCH</div>${(o.m.reasons||[]).slice(0,3).map(q=>`<span class="reason">✓ ${esc(q)}</span>`).join('')}<br><button class="secondary" onclick="compareItems(${o.x.id},${o.m.id})">Compare</button></div>`).join('')||'<p>No match opportunities yet.</p>';let ar=[];for(const x of items.slice(0,4)){let r=await fetch('/api/items/'+x.id+'/activity');let d=await r.json();if(d[0])ar.push(d[0])}$('recentActivity').innerHTML=ar.length?ar.map(x=>`<div style="margin:7px 0"><b>${esc(x.action)}</b><br><small>${esc(x.created_at)}</small></div>`).join(''):'No activity yet';let pr=await fetch('/api/profile');let p=await pr.json();$('profileMini').innerHTML=`<b>${esc(p.full_name)}</b><br>${p.returned} returned · ${p.points} points`;}

function openSheet(title,text,body,onOk){$('sheetTitle').innerText=title;$('sheetText').innerText=text;$('sheetBody').innerHTML=body;$('sheetOk').onclick=onOk;$('sheetBackdrop').classList.add('open');$('actionSheet').classList.add('open')}
function closeSheet(){$('sheetBackdrop').classList.remove('open');$('actionSheet').classList.remove('open')}
function smartConfirm(title,text,onYes){openSheet(title,text,'<p style="color:var(--muted)">This action will update the FINDLY record.</p>',()=>{closeSheet();onYes()})}
function suggestSearch(){let q=$('search').value.trim().toLowerCase(),box=$('suggestions');if(!q){box.classList.remove('show');return}let vals=[...new Set(items.flatMap(x=>[x.item_name,x.category,x.location,x.record_type]).filter(Boolean))].filter(x=>x.toLowerCase().includes(q)).slice(0,6);box.innerHTML=vals.map(x=>`<div class="suggestion" onclick="pickSuggestion('${esc(x).replace(/'/g,'&#039;')}')">🔎 ${esc(x)}</div>`).join('');box.classList.toggle('show',vals.length>0)}
function pickSuggestion(v){$('search').value=v;$('suggestions').classList.remove('show');display()}
function showSkeleton(id,count=3){$(id).innerHTML=Array.from({length:count},()=>'<div class="skeleton" style="width:'+Math.round(60+Math.random()*35)+'%"></div>').join('')}
async function loadUsers(){if(!user||user.role!='Admin'){if($('userManagement'))$('userManagement').style.display='none';return}let r=await fetch('/api/users');if(!r.ok)return;let a=await r.json();$('usersAdmin').innerHTML='<div class="table"><table style="min-width:600px"><thead><tr><th>Name</th><th>Username</th><th>Role</th><th>Reports</th></tr></thead><tbody>'+a.map(x=>`<tr><td>${esc(x.full_name)}</td><td>${esc(x.username)}</td><td>${esc(x.role)}</td><td>${x.reports}</td></tr>`).join('')+'</tbody></table></div>'}
function resetForm(h=true){$('form').reset();editId=null;$('ft').innerText='Report Lost / Found Item';$('save').innerText='Save Item';$('date').value=new Date().toISOString().slice(0,10);$('prev').style.display='none';if(h)$('matches').style.display='none'}function clearFilters(){['search','ftype','fcat','floc','fstatus','fdate'].forEach(x=>$(x).value='');$('sort').value='new';display()}async function noti(){let r=await fetch('/api/notifications');if(!r.ok)return;let d=await r.json();$('nc').innerText=d.unread;if(d.unread>0)island('warn','NOTIFICATION', d.unread+' new notification'+(d.unread>1?'s':''), 'Tap the bell to view updates');$('nl').innerHTML=d.notifications.length?d.notifications.map(n=>`<p><b>${esc(n.notification_type)}</b><br>${esc(n.message)}<br><small>${esc(n.created_at)}</small></p>`).join(''):'No notifications'}function toggleNoti(){$('noti').style.display=$('noti').style.display=='block'?'none':'block';noti()}async function readNoti(){await fetch('/api/notifications/read',{method:'PUT'});noti()}function dark(){document.body.classList.toggle('dark');localStorage.setItem('dark',document.body.classList.contains('dark')?'1':'0')}if(localStorage.getItem('dark')=='1')document.body.classList.add('dark');$('date').value=new Date().toISOString().slice(0,10);setTimeout(()=>island('normal','FINDLY','Smart Lost & Found','AI-style matching is ready'),500);session();
</script></body></html>'''

if __name__=='__main__':
    port=int(os.environ.get('PORT',5000))
    print('FINDLY - SMART LOST & FOUND')
    print('Open: http://127.0.0.1:'+str(port))
    app.run(host='0.0.0.0',port=port,debug=False,use_reloader=False)

