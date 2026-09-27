from __future__ import annotations
import json,threading
from pathlib import Path

DEFAULTS={
    'onboarding_complete':False,
    'preferred_name':'',
    'wake_phrase':'Hey Personal',
    'launch_voice_on_start':False,
    'show_memory_hints':True,
    'reduce_motion':False,
    'high_contrast':False,
    'autonomy_mode':'ask',
}

class Preferences:
    def __init__(self,path:Path):self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True);self.lock=threading.RLock();self.data=dict(DEFAULTS);self._load()
    def _load(self):
        if not self.path.exists():return
        try:
            value=json.loads(self.path.read_text())
            if isinstance(value,dict):self.data.update({k:v for k,v in value.items() if k in DEFAULTS})
        except Exception:pass
    def get(self,key,default=None):return self.data.get(key,default)
    def set(self,key,value):
        if key not in DEFAULTS:raise KeyError(key)
        with self.lock:self.data[key]=value;self._save()
    def update(self,**values):
        unknown=set(values)-set(DEFAULTS)
        if unknown:raise KeyError(sorted(unknown))
        with self.lock:self.data.update(values);self._save()
    def _save(self):
        tmp=self.path.with_suffix('.tmp');tmp.write_text(json.dumps(self.data,sort_keys=True,indent=2));tmp.replace(self.path)
    def snapshot(self):return dict(self.data)
