from __future__ import annotations
import re,time

class WakePhraseGate:
    """Transcript-level wake phrase gate for the active microphone session.

    This is intentionally separate from the low-level audio transport. It provides the
    'Hey Personal' UX without introducing a privileged always-listening native service.
    A future low-power acoustic detector can feed the same `accept()` contract.
    """
    def __init__(self,events=None,phrases=None,window_seconds:float=8.0):
        self.events=events;self.phrases=tuple((phrases or ('hey personal','personal ai')));self.window_seconds=float(window_seconds);self.awake_until=0.0
    def accept(self,text:str,now:float|None=None):
        now=time.monotonic() if now is None else now;raw=' '.join(str(text or '').strip().split());lower=raw.lower()
        for phrase in self.phrases:
            m=re.search(r'(?<!\w)'+re.escape(phrase.lower())+r'(?!\w)',lower)
            if m:
                self.awake_until=now+self.window_seconds
                remainder=raw[m.end():].lstrip(' ,.:;-')
                if self.events:self.events.emit('voice.wake',phrase=phrase,remainder=remainder)
                return {'awake':True,'triggered':True,'phrase':phrase,'command':remainder}
        return {'awake':now<=self.awake_until,'triggered':False,'phrase':None,'command':raw if now<=self.awake_until else ''}
    def reset(self):self.awake_until=0.0
