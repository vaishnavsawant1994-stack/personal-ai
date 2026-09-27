from datetime import datetime
from tools.registry import Tool, Risk

def register(reg,store):
    def create(p):
        title=str(p["title"]); due=str(p.get("due_at","")); import uuid, json; i=str(uuid.uuid4())
        with store.lock, store.con() as c:
            c.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?)",(i,title,"pending",due,json.dumps(p.get("payload",{})),datetime.utcnow().isoformat()))
        return {"ok":True,"task_id":i}
    reg.register(Tool("create_reminder","Create reminder/task; params: title,due_at,payload",create,Risk.REVERSIBLE))
