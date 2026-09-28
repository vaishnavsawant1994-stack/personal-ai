from concurrent.futures import ThreadPoolExecutor
import json,time
from future_intelligence.autonomy import AdvancedAutonomy
from future_intelligence.autonomy_runtime import install
from recovery.backup import BACKUP_MAGIC,BackupService
install(AdvancedAutonomy)
class D: allowed=True; reason='ok'
class G:
    def decision(self,_): return D()
class Key:
    def get_or_create(self): return b'7'*32

def make(path): return AdvancedAutonomy(gate=G(),path=path)

def test_p10_concurrent_goal_isolation_and_event_writes(tmp_path):
    a=make(tmp_path/'a.db')
    def one(i):
        owner=f'o{i%8}'; g=a.create_goal(f'g{i}',owner_id=owner); p=a.create_plan(g['id'],[{'id':'a'},{'id':'b'}],owner_id=owner); return g['id'],p['id'],owner,a.plan(p['id'],owner_id=owner)['owner_id']
    with ThreadPoolExecutor(max_workers=8) as pool: out=list(pool.map(one,range(80)))
    assert len(out)==80 and all(owner==seen for _,_,owner,seen in out)
    assert len({g for g,_,_,_ in out})==80 and len({p for _,p,_,_ in out})==80
    with a._lock:
        assert a._db.execute('select count(*) from p10_goals').fetchone()[0]==80
        assert a._db.execute('select count(*) from p10_plans').fetchone()[0]==80
        assert a._db.execute('pragma integrity_check').fetchone()[0]=='ok'

def test_p10_repeated_concurrent_reads_writes_and_owner_isolation(tmp_path):
    a=make(tmp_path/'stress.db')
    def one(i):
        owner=f'owner-{i%6}'; g=a.create_goal(f'stress-{i}',owner_id=owner); p=a.create_plan(g['id'],[{'id':'first'},{'id':'second','dependencies':['first']}],owner_id=owner)
        for n in range(3):
            assert a.goal(g['id'],owner_id=owner)['owner_id']==owner
            assert a.plan(p['id'],owner_id=owner)['owner_id']==owner
            a._event('stress_tick',goal_id=g['id'],plan_id=p['id'],iteration=n,metadata={'secret':'must-not-persist','safe':'ok'})
        try: a.plan(p['id'],owner_id='wrong-owner')
        except KeyError: pass
        else: raise AssertionError('cross-owner plan read was allowed')
        return g['id'],p['id']
    for _ in range(3):
        with ThreadPoolExecutor(max_workers=12) as pool: rows=list(pool.map(one,range(60)))
        assert len(rows)==60
    with a._lock:
        assert a._db.execute('pragma integrity_check').fetchone()[0]=='ok'
        assert a._db.execute('select count(*) from p10_events').fetchone()[0] <= a.MAX_HISTORY
        leaked=a._db.execute("select count(*) from p10_events where safe_json like '%must-not-persist%'").fetchone()[0]
        assert leaked==0

def test_p10_durable_states_and_restart_uncertainty(tmp_path):
    path=tmp_path/'a.db'; a=make(path); g=a.create_goal('durable'); ready=a.create_plan(g['id'],[{'id':'r'}]); paused=a.create_plan(g['id'],[{'id':'p'}]); a.pause(paused['id']); active=a.create_plan(g['id'],[{'id':'x'}]); a.mark_task(active['id'],'x','running'); cancelled=a.create_plan(g['id'],[{'id':'c'}]); a.cancel(cancelled['id']); b=make(path)
    assert b.plan(ready['id'])['state']=='READY'; assert b.plan(paused['id'])['state']=='PAUSED'; assert b.plan(active['id'])['state']=='UNCERTAIN'; assert b.plan(cancelled['id'])['state']=='CANCELLED'
    with b._lock: assert b._db.execute('pragma integrity_check').fetchone()[0]=='ok'

def test_p10_history_and_context_bounds(tmp_path):
    a=make(tmp_path/'a.db'); g=a.create_goal('bounded')
    for i in range(700): a._event('tick',goal_id=g['id'],index=i)
    with a._lock: assert a._db.execute('select count(*) from p10_events').fetchone()[0] <= a.MAX_HISTORY
    c=a.context_projection(g['id'],memory_items=['x'*5000]*100,knowledge_items=['y'*5000]*100,world_items=['z'*5000]*100,limit=20)
    assert all(len(v)==20 for v in (c['memory'],c['knowledge'],c['world'])) and max(map(len,c['memory']))<=1000

def test_p10_encrypted_backup_restore_preserves_durable_state(tmp_path):
    source=tmp_path/'source'; target=tmp_path/'target'; source.mkdir(); target.mkdir(); db=source/'autonomy.sqlite3'; a=make(db); g=a.create_goal('backup'); p=a.create_plan(g['id'],[{'id':'a'}]); a.cancel(p['id']); a._db.close()
    archive=BackupService(source,root_key_store=Key()).create('p10.paibackup'); raw=archive.read_bytes(); assert raw.startswith(BACKUP_MAGIC) and b'backup' not in raw
    assert BackupService(source,root_key_store=Key()).inspect(archive)['encrypted'] is True
    restored=BackupService(target,root_key_store=Key()).restore(archive); assert restored['ok'] and restored['encrypted']; b=make(target/'autonomy.sqlite3'); assert b.plan(p['id'])['state']=='CANCELLED'

def test_p10_performance_envelope_is_bounded_and_reported(tmp_path):
    a=make(tmp_path/'a.db'); start=time.perf_counter(); goals=[a.create_goal(f'g{i}') for i in range(100)]; goal_s=time.perf_counter()-start
    start=time.perf_counter(); plans=[a.create_plan(g['id'],[{'id':'a'},{'id':'b','dependencies':['a']}]) for g in goals]; plan_s=time.perf_counter()-start
    start=time.perf_counter(); [a.ready_tasks(p['id']) for p in plans for _ in range(10)]; ready_s=time.perf_counter()-start
    start=time.perf_counter(); make(tmp_path/'a.db'); restart_s=time.perf_counter()-start
    with a._lock: events=a._db.execute('select count(*) from p10_events').fetchone()[0]
    metrics={'goal_100_seconds':round(goal_s,6),'plan_100_seconds':round(plan_s,6),'ready_1000_seconds':round(ready_s,6),'restart_seconds':round(restart_s,6),'events':events}
    assert goal_s<5 and plan_s<5 and ready_s<5 and restart_s<1 and metrics['events']<=a.MAX_HISTORY
    print('P10_PERFORMANCE_RESULTS='+json.dumps(metrics,sort_keys=True),flush=True)