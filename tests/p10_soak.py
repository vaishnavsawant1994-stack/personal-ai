from __future__ import annotations
import argparse,json,os,sys,tempfile,time
from pathlib import Path
try:
 import psutil
except Exception: psutil=None
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from future_intelligence.autonomy import AdvancedAutonomy
from future_intelligence.autonomy_runtime import install
install(AdvancedAutonomy)
class D: allowed=True; reason='ok'
class G:
 def decision(self,_): return D()

def rss(): return psutil.Process(os.getpid()).memory_info().rss if psutil else 0

def main(seconds):
 root=Path(tempfile.mkdtemp(prefix='p10-soak-')); a=AdvancedAutonomy(gate=G(),path=root/'a.db'); start=time.monotonic(); r0=rss(); peak=r0; iterations=success=blocked=cancelled=replans=uncertain=0
 while time.monotonic()-start<seconds:
  i=iterations; g=a.create_goal(f'g{i}',allowed_capabilities=['read']); p=a.create_plan(g['id'],[{'id':'read','required_capabilities':['read']},{'id':'analyze','dependencies':['read'],'verification_required':i%7==0}]); a.mark_task(p['id'],'read','completed',verified=True)
  if i%7==0:
   p=a.mark_task(p['id'],'analyze','completed',verified=False); uncertain+=int(p['state']=='UNCERTAIN')
  elif i%5==0:
   a.cancel(p['id']); cancelled+=1
  elif i%3==0:
   a.replan(p['id'],[{'id':'read2','required_capabilities':['read']}]); replans+=1; a.mark_task(p['id'],'read2','completed',verified=True); success+=1
  else:
   a.mark_task(p['id'],'analyze','completed',verified=True); success+=1
  if i%11==0:
   try: a.create_plan(g['id'],[{'id':'x'},{'id':'x'}])
   except ValueError: blocked+=1
  iterations+=1; peak=max(peak,rss())
 r1=rss()
 with a._lock:
  events=a._db.execute('select count(*) from p10_events').fetchone()[0]; goals=a._db.execute('select count(*) from p10_goals').fetchone()[0]; plans=a._db.execute('select count(*) from p10_plans').fetchone()[0]; integrity=a._db.execute('PRAGMA integrity_check').fetchone()[0]
 out={'seconds':seconds,'iterations':iterations,'success':success,'expected_blocked':blocked,'cancelled':cancelled,'replans':replans,'uncertain':uncertain,'rss_start':r0,'rss_peak':peak,'rss_end':r1,'rss_growth':max(0,r1-r0),'events_retained':events,'goals':goals,'plans':plans,'sqlite_integrity':integrity}
 assert iterations>0 and events<=a.MAX_HISTORY and blocked>0 and uncertain>0 and integrity=='ok'
 print('P10_SOAK_RESULTS='+json.dumps(out,sort_keys=True),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser(); p.add_argument('--seconds',type=int,default=45); args=p.parse_args(); main(args.seconds)