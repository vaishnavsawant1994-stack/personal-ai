from __future__ import annotations
import hashlib,io
class DesktopController:
    def __init__(self,pause=.15):self.pause=pause
    def _pg(self):import pyautogui; pyautogui.PAUSE=self.pause; pyautogui.FAILSAFE=True; return pyautogui
    def position(self):p=self._pg().position(); return {'x':p.x,'y':p.y}
    def snapshot(self):
        pg=self._pg(); im=pg.screenshot(); b=io.BytesIO(); im.save(b,format='PNG'); p=pg.position(); return {'x':p.x,'y':p.y,'screen_sha256':hashlib.sha256(b.getvalue()).hexdigest()}
    def verify_change(self,before,after,kind):return before['screen_sha256']!=after['screen_sha256'] or kind=='move'
    def undo_descriptor(self,kind,before,params):
        if kind=='move':return {'kind':'move','x':before['x'],'y':before['y']}
        if kind=='type_text':return {'kind':'hotkey','keys':['ctrl','z']}
        if kind=='hotkey' and tuple(params.get('keys',())) in {('ctrl','c'),('command','c')}:return None
        return None
    def apply_undo(self,d):
        if d['kind']=='move':return self.move(d['x'],d['y'])
        if d['kind']=='hotkey':return self.hotkey(*d['keys'])
        return {'ok':False}
    def move(self,x,y,duration=.2):self._pg().moveTo(int(x),int(y),duration=float(duration)); return self.position()
    def click(self,x=None,y=None,button='left'):
        if x is None or y is None: raise ValueError('desktop click requires explicit coordinates')
        if str(button) not in {'left','middle','right'}: raise ValueError('desktop click button is not allowed')
        self._pg().click(x=int(x),y=int(y),button=str(button)); return {'ok':True}
    def type_text(self,text,interval=.01):
        value=str(text)
        if not value or len(value)>8000: raise ValueError('desktop type requires 1-8000 characters')
        delay=float(interval)
        if delay < 0 or delay > 1: raise ValueError('desktop type interval is outside the allowed range')
        self._pg().write(value,interval=delay); return {'ok':True}
    def hotkey(self,*keys):
        bounded=tuple(str(key).lower() for key in keys)
        if not 1<=len(bounded)<=5 or any(not key or len(key)>24 for key in bounded): raise ValueError('desktop hotkey requires 1-5 bounded key names')
        self._pg().hotkey(*bounded); return {'ok':True}
    def screenshot(self,path):self._pg().screenshot(path); return {'path':str(path)}
