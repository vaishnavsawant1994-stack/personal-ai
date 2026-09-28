from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid


class GoalState(str, Enum):
    CREATED='CREATED'; PLANNING='PLANNING'; READY='READY'; RUNNING='RUNNING'; PAUSED='PAUSED'; BLOCKED='BLOCKED'; COMPLETED='COMPLETED'; FAILED='FAILED'; CANCELLED='CANCELLED'; UNCERTAIN='UNCERTAIN'


class PlanState(str, Enum):
    CREATED='CREATED'; VALIDATING='VALIDATING'; READY='READY'; WAITING='WAITING'; WAITING_APPROVAL='WAITING_APPROVAL'; RUNNING='RUNNING'; VERIFYING='VERIFYING'; RECOVERING='RECOVERING'; PAUSED='PAUSED'; BLOCKED='BLOCKED'; COMPLETED='COMPLETED'; FAILED='FAILED'; CANCELLED='CANCELLED'; UNCERTAIN='UNCERTAIN'


TERMINAL={PlanState.COMPLETED.value,PlanState.FAILED.value,PlanState.CANCELLED.value,PlanState.UNCERTAIN.value}


@dataclass
class Goal:
    id:str; owner_id:str; description:str; desired_outcome:str=''; request_id:str|None=None; session_id:str|None=None
    constraints:list[str]=field(default_factory=list); priority:int=50; deadline:str|None=None; privacy:str='internal'; risk:str='low'
    allowed_capabilities:list[str]=field(default_factory=list); prohibited_actions:list[str]=field(default_factory=list)
    success_criteria:list[str]=field(default_factory=list); failure_criteria:list[str]=field(default_factory=list); dependencies:list[str]=field(default_factory=list)
    state:str=GoalState.CREATED.value; created_at:float=field(default_factory=time.time); updated_at:float=field(default_factory=time.time)


class AdvancedAutonomy:
    """P10 canonical orchestration layer.

    This layer owns goals/plans/orchestration state only. It never owns identity,
    permissions, approvals, tool execution, verification, recovery, model routing,
    memory, knowledge, continuity, or Emergency Stop authority.
    """
    MAX_TASKS=50; MAX_DEPTH=5; MAX_REPLANS=5; MAX_RETRIES=3; MAX_HISTORY=500

    def __init__(self,*,gate,operations=None,events=None,path:Path|None=None,executor=None,automations=None,models=None,memory=None,knowledge=None,world=None,continuity=None,emergency_stop_provider=None):
        self.gate=gate; self.operations=operations; self.events=events; self.executor=executor; self.automations=automations; self.models=models
        self.memory=memory; self.knowledge=knowledge; self.world=world; self.continuity=continuity; self.emergency_stop_provider=emergency_stop_provider
        self._agents={}; self._outcomes=[]; self._db=None; self._lock=threading.RLock(); self._local_stop=False
        if path is not None:
            path=Path(path); path.parent.mkdir(parents=True,exist_ok=True); self._db=sqlite3.connect(path,check_same_thread=False,timeout=30); self._db.row_factory=sqlite3.Row
            self._db.executescript('''
                CREATE TABLE IF NOT EXISTS agents (id TEXT PRIMARY KEY, document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS autonomy_outcomes (id INTEGER PRIMARY KEY AUTOINCREMENT, document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS autonomy_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS p10_goals (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, document TEXT NOT NULL, updated_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS p10_plans (id TEXT PRIMARY KEY, goal_id TEXT NOT NULL, owner_id TEXT NOT NULL, state TEXT NOT NULL, document TEXT NOT NULL, updated_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS p10_events (id INTEGER PRIMARY KEY AUTOINCREMENT, goal_id TEXT, plan_id TEXT, kind TEXT NOT NULL, safe_json TEXT NOT NULL, created_at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS idx_p10_plans_goal ON p10_plans(goal_id,updated_at);
                CREATE INDEX IF NOT EXISTS idx_p10_events_goal ON p10_events(goal_id,created_at);
            ''')
            self._agents={row[0]:json.loads(row[1]) for row in self._db.execute('SELECT id,document FROM agents')}
            self._outcomes=[json.loads(row[0]) for row in self._db.execute('SELECT document FROM autonomy_outcomes ORDER BY id DESC LIMIT 500')][::-1]
            row=self._db.execute("SELECT value FROM autonomy_state WHERE key='emergency_stop'").fetchone(); self._local_stop=bool(row and row[0]=='1')
            self._recover_after_restart()

    def _canonical_stop_active(self):
        if self.emergency_stop_provider is not None:
            try: return bool(self.emergency_stop_provider())
            except Exception: return True
        return self._local_stop

    def _emit(self,name,**payload):
        if self.events: self.events.emit(name,**payload)

    def _event(self,kind,*,goal_id=None,plan_id=None,**safe):
        clean={k:v for k,v in safe.items() if k not in {'prompt','memory','knowledge','secret','token','approval_token','raw_context'}}
        if self._db is not None:
            self._db.execute('INSERT INTO p10_events(goal_id,plan_id,kind,safe_json,created_at) VALUES(?,?,?,?,?)',(goal_id,plan_id,kind,json.dumps(clean,default=str,sort_keys=True)[:4000],time.time()))
            self._db.execute('DELETE FROM p10_events WHERE id NOT IN (SELECT id FROM p10_events ORDER BY id DESC LIMIT ?)',(self.MAX_HISTORY,)); self._db.commit()
        self._emit('p10.'+kind,goal_id=goal_id,plan_id=plan_id,**clean)

    def _save_agent(self,agent):
        if self._db is not None:
            self._db.execute('INSERT OR REPLACE INTO agents(id,document) VALUES(?,?)',(agent['id'],json.dumps(agent,sort_keys=True))); self._db.commit()

    def _save_goal(self,goal:dict):
        goal['updated_at']=time.time()
        if self._db is not None:
            self._db.execute('INSERT OR REPLACE INTO p10_goals(id,owner_id,document,updated_at) VALUES(?,?,?,?)',(goal['id'],goal['owner_id'],json.dumps(goal,sort_keys=True),goal['updated_at'])); self._db.commit()
        return goal

    def _save_plan(self,plan):
        plan['updated_at']=time.time()
        if self._db is not None:
            self._db.execute('INSERT OR REPLACE INTO p10_plans(id,goal_id,owner_id,state,document,updated_at) VALUES(?,?,?,?,?,?)',(plan['id'],plan['goal_id'],plan['owner_id'],plan['state'],json.dumps(plan,sort_keys=True),plan['updated_at'])); self._db.commit()
        return plan

    def _recover_after_restart(self):
        if self._db is None:return
        rows=self._db.execute("SELECT id,document FROM p10_plans WHERE state IN ('RUNNING','VERIFYING','RECOVERING')").fetchall()
        for row in rows:
            plan=json.loads(row['document']); plan['state']=PlanState.UNCERTAIN.value; plan['restart_reason']='runtime restarted during active work; existing verification/recovery authority must resolve before continuation'; self._save_plan(plan)

    def emergency_stop(self,reason:str='owner requested'):
        # Compatibility shim only; canonical deployments should supply emergency_stop_provider.
        self._local_stop=True
        for agent in self._agents.values(): agent['enabled']=False; self._save_agent(agent)
        if self._db is not None:
            self._db.execute("INSERT OR REPLACE INTO autonomy_state(key,value) VALUES('emergency_stop','1')"); self._db.execute("UPDATE p10_plans SET state='BLOCKED' WHERE state NOT IN ('COMPLETED','FAILED','CANCELLED','UNCERTAIN')"); self._db.commit()
        self._event('emergency_stop',reason=reason); return {'stopped':True,'reason':reason}

    def clear_emergency_stop(self):
        self._local_stop=False
        if self._db is not None:self._db.execute("INSERT OR REPLACE INTO autonomy_state(key,value) VALUES('emergency_stop','0')");self._db.commit()
        return {'stopped':False,'note':'clearing the compatibility flag does not restore stale work or approvals'}

    def status(self):
        goals=plans=0
        if self._db is not None:
            goals=self._db.execute('SELECT COUNT(*) FROM p10_goals').fetchone()[0]; plans=self._db.execute('SELECT COUNT(*) FROM p10_plans').fetchone()[0]
        return {'emergency_stop':self._canonical_stop_active(),'agents':list(self._agents.values()),'goals':goals,'plans':plans,'authority':'orchestration_only'}

    def create_goal(self,description:str,*,owner_id='owner',desired_outcome='',request_id=None,session_id=None,constraints=None,priority=50,deadline=None,privacy='internal',risk='low',allowed_capabilities=None,prohibited_actions=None,success_criteria=None,failure_criteria=None,dependencies=None):
        if not str(description).strip(): raise ValueError('goal description required')
        g=Goal(id=str(uuid.uuid4()),owner_id=str(owner_id),description=str(description)[:4000],desired_outcome=str(desired_outcome)[:2000],request_id=request_id,session_id=session_id,constraints=list(constraints or [])[:30],priority=max(0,min(int(priority),100)),deadline=deadline,privacy=str(privacy),risk=str(risk),allowed_capabilities=list(dict.fromkeys(allowed_capabilities or []))[:50],prohibited_actions=list(dict.fromkeys(prohibited_actions or []))[:50],success_criteria=list(success_criteria or [])[:30],failure_criteria=list(failure_criteria or [])[:30],dependencies=list(dict.fromkeys(dependencies or []))[:50])
        out=asdict(g); self._save_goal(out); self._event('goal_created',goal_id=g.id,owner_id=g.owner_id,risk=g.risk,privacy=g.privacy); return out

    def goal(self,goal_id,*,owner_id=None):
        if self._db is None: raise KeyError('goal store not configured')
        row=self._db.execute('SELECT owner_id,document FROM p10_goals WHERE id=?',(goal_id,)).fetchone()
        if not row or (owner_id is not None and row['owner_id']!=owner_id): raise KeyError('goal not found')
        return json.loads(row['document'])

    def _validate_tasks(self,tasks,parent_goal):
        if not isinstance(tasks,list) or len(tasks)>self.MAX_TASKS: raise ValueError('task decomposition exceeds bounded task count')
        ids=set(); clean=[]
        parent_caps=set(parent_goal.get('allowed_capabilities') or [])
        prohibited=set(parent_goal.get('prohibited_actions') or [])
        for i,item in enumerate(tasks):
            if not isinstance(item,dict): raise ValueError('task must be an object')
            tid=str(item.get('id') or f't{i+1}')[:80]
            if tid in ids:
                raise ValueError('duplicate task id')
            ids.add(tid)
            depth=max(1,int(item.get('depth',1)))
            if depth>self.MAX_DEPTH: raise ValueError('decomposition depth exceeded')
            deps=list(dict.fromkeys(str(x)[:80] for x in item.get('dependencies',[])))[:self.MAX_TASKS]
            caps=list(dict.fromkeys(str(x) for x in item.get('required_capabilities',[])))[:20]
            if parent_caps and not set(caps).issubset(parent_caps): raise PermissionError('child task cannot expand parent capabilities')
            action=str(item.get('action',''))[:200]
            if action and action in prohibited: raise PermissionError('child task requests prohibited action')
            clean.append({'id':tid,'objective':str(item.get('objective',''))[:1000],'dependencies':deps,'required_capabilities':caps,'action':action,'depth':depth,'risk':str(item.get('risk',parent_goal.get('risk','low'))),'privacy':str(item.get('privacy',parent_goal.get('privacy','internal'))),'consequential':bool(item.get('consequential',False)),'approval_required':bool(item.get('approval_required',False)),'verification_required':bool(item.get('verification_required',False)),'retry_limit':max(0,min(int(item.get('retry_limit',0)),self.MAX_RETRIES)),'status':'WAITING','result_ref':None})
        known={x['id'] for x in clean}
        for item in clean:
            if item['id'] in item['dependencies'] or any(x not in known for x in item['dependencies']): raise ValueError('invalid task dependency')
        self._assert_acyclic(clean); return clean

    @staticmethod
    def _assert_acyclic(tasks):
        graph={x['id']:x['dependencies'] for x in tasks}; visiting=set(); done=set()
        def visit(node):
            if node in visiting: raise ValueError('dependency cycle detected')
            if node in done:return
            visiting.add(node)
            for dep in graph[node]:visit(dep)
            visiting.remove(node);done.add(node)
        for node in graph:visit(node)

    def create_plan(self,goal_id,tasks,*,owner_id='owner'):
        goal=self.goal(goal_id,owner_id=owner_id); clean=self._validate_tasks(tasks,goal); stamp=time.time()
        plan={'id':str(uuid.uuid4()),'goal_id':goal_id,'owner_id':owner_id,'state':PlanState.READY.value,'tasks':clean,'replan_count':0,'created_at':stamp,'updated_at':stamp,'security_epoch':None,'device_id':None,'session_id':goal.get('session_id')}
        self._save_plan(plan); goal['state']=GoalState.READY.value; self._save_goal(goal); self._event('plan_ready',goal_id=goal_id,plan_id=plan['id'],task_count=len(clean)); return plan

    def plan(self,plan_id,*,owner_id=None):
        if self._db is None: raise KeyError('plan store not configured')
        row=self._db.execute('SELECT owner_id,document FROM p10_plans WHERE id=?',(plan_id,)).fetchone()
        if not row or (owner_id is not None and row['owner_id']!=owner_id): raise KeyError('plan not found')
        return json.loads(row['document'])

    def ready_tasks(self,plan_id,*,owner_id=None):
        plan=self.plan(plan_id,owner_id=owner_id); completed={x['id'] for x in plan['tasks'] if x['status']=='COMPLETED'}
        return [x for x in plan['tasks'] if x['status']=='WAITING' and set(x['dependencies']).issubset(completed)]

    def replan(self,plan_id,replacement_tasks,*,owner_id='owner',reason='changed conditions'):
        plan=self.plan(plan_id,owner_id=owner_id)
        if plan['replan_count']>=self.MAX_REPLANS: plan['state']=PlanState.BLOCKED.value; self._save_plan(plan); raise RuntimeError('replan limit exceeded')
        goal=self.goal(plan['goal_id'],owner_id=owner_id); clean=self._validate_tasks(replacement_tasks,goal); plan['tasks']=clean; plan['replan_count']+=1; plan['state']=PlanState.READY.value; self._save_plan(plan); self._event('replanned',goal_id=plan['goal_id'],plan_id=plan_id,replan_count=plan['replan_count'],reason=str(reason)[:300]); return plan

    def pause(self,plan_id,*,owner_id='owner'):
        plan=self.plan(plan_id,owner_id=owner_id)
        if plan['state'] not in TERMINAL: plan['state']=PlanState.PAUSED.value; self._save_plan(plan); self._event('paused',goal_id=plan['goal_id'],plan_id=plan_id)
        return plan

    def resume(self,plan_id,*,owner_id='owner'):
        plan=self.plan(plan_id,owner_id=owner_id)
        if self._canonical_stop_active(): raise PermissionError('Emergency Stop active')
        if plan['state'] not in {PlanState.PAUSED.value,PlanState.BLOCKED.value}: raise RuntimeError('plan is not resumable')
        plan['state']=PlanState.READY.value; self._save_plan(plan); self._event('resumed',goal_id=plan['goal_id'],plan_id=plan_id); return plan

    def cancel(self,plan_id,*,owner_id='owner',reason='owner cancelled'):
        plan=self.plan(plan_id,owner_id=owner_id); plan['state']=PlanState.CANCELLED.value
        for task in plan['tasks']:
            if task['status'] in {'WAITING','READY'}:task['status']='CANCELLED'
        self._save_plan(plan); goal=self.goal(plan['goal_id'],owner_id=owner_id); goal['state']=GoalState.CANCELLED.value; self._save_goal(goal); self._event('cancelled',goal_id=plan['goal_id'],plan_id=plan_id,reason=str(reason)[:300]); return plan

    def mark_task(self,plan_id,task_id,status,*,owner_id='owner',result_ref=None,verified=None):
        plan=self.plan(plan_id,owner_id=owner_id); task=next((x for x in plan['tasks'] if x['id']==task_id),None)
        if task is None: raise KeyError('task not found')
        if task['consequential'] and self._canonical_stop_active(): raise PermissionError('Emergency Stop blocks consequential work')
        status=str(status).upper()
        if status=='COMPLETED' and task['verification_required'] and verified is not True: status='UNCERTAIN'
        task['status']=status; task['result_ref']=str(result_ref)[:500] if result_ref is not None else None
        if status=='UNCERTAIN': plan['state']=PlanState.UNCERTAIN.value
        elif all(x['status']=='COMPLETED' for x in plan['tasks']): plan['state']=PlanState.COMPLETED.value
        else: plan['state']=PlanState.RUNNING.value
        self._save_plan(plan); self._event('task_state',goal_id=plan['goal_id'],plan_id=plan_id,task_id=task_id,status=status,verified=verified); return plan

    def proactive_suggestion(self,goal_id,message,*,owner_id='owner',consequential=False):
        self.goal(goal_id,owner_id=owner_id); suggestion={'goal_id':goal_id,'message':str(message)[:1000],'kind':'SUGGESTION','action_authority':False,'consequential':bool(consequential)}; self._event('suggestion',goal_id=goal_id,consequential=bool(consequential)); return suggestion

    def context_projection(self,goal_id,*,owner_id='owner',memory_items=None,knowledge_items=None,world_items=None,limit=8):
        goal=self.goal(goal_id,owner_id=owner_id); limit=max(0,min(int(limit),20))
        def bounded(items): return [str(x)[:1000] for x in list(items or [])[:limit]]
        return {'goal_id':goal_id,'privacy':goal['privacy'],'memory':bounded(memory_items),'knowledge':bounded(knowledge_items),'world':bounded(world_items),'authority':False}

    def record_lesson(self,goal_id,kind,summary,*,owner_id='owner',evidence_ref=None):
        self.goal(goal_id,owner_id=owner_id); allowed={'workflow_succeeded','workflow_failed','tool_unreliable','provider_slow','plan_inefficient','owner_correction','verification_failed','recovery_needed'}
        if kind not in allowed: raise ValueError('unsupported lesson kind')
        return self.record_outcome(kind,str(summary)[:1000],success=kind=='workflow_succeeded',evidence={'goal_id':goal_id,'evidence_ref':str(evidence_ref)[:300] if evidence_ref else None,'policy_mutation':False,'source_code_mutation':False})

    def create_agent(self,name:str,mission:str,skills:list[str]):
        if not name.strip() or not mission.strip():raise ValueError('name and mission required')
        aid=str(uuid.uuid4()); self._agents[aid]={'id':aid,'name':name.strip(),'mission':mission.strip(),'skills':list(dict.fromkeys(skills))[:20],'enabled':False,'tool_allowlist':[],'budget_limit':0,'authority':'worker_only'}; self._save_agent(self._agents[aid]); return self._agents[aid]

    def set_policy(self,agent_id:str,*,tool_allowlist:list[str],budget_limit:float):
        if agent_id not in self._agents:raise KeyError('agent not found')
        agent=self._agents[agent_id]; agent['tool_allowlist']=list(dict.fromkeys(tool_allowlist))[:50]; agent['budget_limit']=max(0,float(budget_limit)); self._save_agent(agent); return agent

    def enable_agent(self,agent_id:str):
        if self._canonical_stop_active():return {'enabled':False,'blocked':True,'reason':'owner emergency stop is active'}
        d=self.gate.decision('p10')
        if not d.allowed:return {'enabled':False,'blocked':True,'reason':d.reason}
        if agent_id not in self._agents:raise KeyError('agent not found')
        self._agents[agent_id]['enabled']=True; self._save_agent(self._agents[agent_id]); return self._agents[agent_id]

    def long_horizon_plan(self,goal:str):
        d=self.gate.decision('p10')
        if not d.allowed:return {'blocked':True,'reason':d.reason,'goal':goal}
        return {'blocked':False,'goal':goal,'stages':['understand','gather_evidence','plan','seek_required_approvals','execute_governed_steps','verify','reflect','update_memory']}

    def record_outcome(self,objective:str,result:str,*,success:bool,evidence:dict|None=None):
        item={'objective':str(objective)[:1000],'result':str(result)[:1000],'success':bool(success),'evidence':dict(evidence or {})}; self._outcomes.append(item); self._outcomes=self._outcomes[-self.MAX_HISTORY:]
        if self._db is not None:
            self._db.execute('INSERT INTO autonomy_outcomes(document) VALUES(?)',(json.dumps(item,sort_keys=True),)); self._db.execute('DELETE FROM autonomy_outcomes WHERE id NOT IN (SELECT id FROM autonomy_outcomes ORDER BY id DESC LIMIT ?)',(self.MAX_HISTORY,)); self._db.commit()
        return item

    def self_evaluation(self):
        total=len(self._outcomes); success=sum(1 for x in self._outcomes if x['success']); return {'samples':total,'success_rate':(success/total if total else None),'outcomes':self._outcomes[-50:]}

    def scenario(self,question:str,options:list[str]):
        return {'question':question,'options':options[:10],'warning':'Scenario analysis is advisory; it must not create authority or execute consequences.'}
