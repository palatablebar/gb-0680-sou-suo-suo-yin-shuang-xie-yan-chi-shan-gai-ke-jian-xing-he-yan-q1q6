import json,sqlite3
from app.errors import DomainError
from app.modules.m8_takedowns.rules import evaluate
def connect(data_dir):
    data_dir.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(data_dir/"takedowns.db",timeout=20)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS takedowns(
        id TEXT PRIMARY KEY,payload TEXT NOT NULL,conclusion TEXT NOT NULL,
        credential_id TEXT,scope_digest TEXT NOT NULL,created_seq INTEGER NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS takedown_events(
        id INTEGER PRIMARY KEY AUTOINCREMENT,ticket_id TEXT NOT NULL,
        conclusion TEXT NOT NULL,credential_id TEXT,payload TEXT NOT NULL)""")
    return db
def settle(data_dir,payload):
    result=evaluate(payload)
    ticket_id=result["ticket_id"]
    with connect(data_dir) as db:
        existing=db.execute("SELECT payload,conclusion,credential_id FROM takedowns WHERE id=?",(ticket_id,)).fetchone()
        if existing:
            stored=json.loads(existing[0])
            if existing[1] in {"已下架","已超时"}:
                return stored,False
            if result["conclusion"]=="处置中":
                return stored,False
            db.execute("UPDATE takedowns SET payload=?,conclusion=?,credential_id=? WHERE id=?",
                (json.dumps(result,ensure_ascii=False),result["conclusion"],result["credential_id"],ticket_id))
            db.execute("INSERT INTO takedown_events(ticket_id,conclusion,credential_id,payload) VALUES(?,?,?,?)",
                (ticket_id,result["conclusion"],result["credential_id"],json.dumps(result,ensure_ascii=False)))
            return result,True
        seq=db.execute("SELECT COALESCE(MAX(created_seq),0)+1 FROM takedowns").fetchone()[0]
        db.execute("INSERT INTO takedowns(id,payload,conclusion,credential_id,scope_digest,created_seq) VALUES(?,?,?,?,?,?)",
            (ticket_id,json.dumps(result,ensure_ascii=False),result["conclusion"],result["credential_id"],result["scope_digest"],seq))
        db.execute("INSERT INTO takedown_events(ticket_id,conclusion,credential_id,payload) VALUES(?,?,?,?)",
            (ticket_id,result["conclusion"],result["credential_id"],json.dumps(result,ensure_ascii=False)))
    return result,True
def get(data_dir,ticket_id):
    with connect(data_dir) as db:
        row=db.execute("SELECT payload FROM takedowns WHERE id=?",(ticket_id,)).fetchone()
    if not row: raise DomainError("NOT_FOUND","下架工单不存在",404)
    return json.loads(row[0])
def history(data_dir):
    with connect(data_dir) as db:
        rows=db.execute("SELECT id,conclusion,credential_id,scope_digest,created_seq FROM takedowns ORDER BY created_seq DESC").fetchall()
    return [{"ticket_id":i,"conclusion":c,"credential_id":cred,"scope_digest":s,"seq":seq} for i,c,cred,s,seq in rows]
def event_count(data_dir,ticket_id):
    with connect(data_dir) as db:
        return db.execute("SELECT COUNT(*) FROM takedown_events WHERE ticket_id=?",(ticket_id,)).fetchone()[0]
