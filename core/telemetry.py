from __future__ import annotations
import json,statistics,threading,time
from collections import defaultdict,deque
from pathlib import Path

class Telemetry:
    """Local-only operational metrics. Never sends data off-device."""
    def __init__(self,path:Path,max_samples:int=500):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True);self.max_samples=max_samples;self.lock=threading.RLock();self.samples=defaultdict(lambda:deque(maxlen=max_samples));self.counters=defaultdict(int);self.started=time.time()
    def observe(self,name:str,value:float):
        with self.lock:self.samples[name].append(float(value))
    def increment(self,name:str,amount:int=1):
        with self.lock:self.counters[name]+=amount
    def timed(self,name:str):return _Timer(self,name)
    def snapshot(self):
        with self.lock:
            metrics={}
            for name,values in self.samples.items():
                seq=list(values)
                if not seq:continue
                ordered=sorted(seq);idx=min(len(ordered)-1,max(0,int(round(.95*(len(ordered)-1)))))
                metrics[name]={'count':len(seq),'avg':round(statistics.fmean(seq),3),'p95':round(ordered[idx],3),'max':round(max(seq),3)}
            return {'uptime_seconds':round(time.time()-self.started,1),'metrics':metrics,'counters':dict(self.counters)}
    def persist(self):
        snap=self.snapshot();tmp=self.path.with_suffix('.tmp');tmp.write_text(json.dumps(snap,sort_keys=True,indent=2));tmp.replace(self.path);return snap

class _Timer:
    def __init__(self,telemetry,name):self.telemetry=telemetry;self.name=name;self.start=0.0
    def __enter__(self):self.start=time.perf_counter();return self
    def __exit__(self,*_):self.telemetry.observe(self.name,(time.perf_counter()-self.start)*1000)
