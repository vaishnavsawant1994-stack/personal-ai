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
    def click(self,x=None,y=None,button='left'):self._pg().click(x=x,y=y,button=button); return {'ok':True}
    def type_text(self,text,interval=.01):self._pg().write(str(text),interval=float(interval)); return {'ok':True}
    def hotkey(self,*keys):self._pg().hotkey(*keys); return {'ok':True}
    def screenshot(self,path):self._pg().screenshot(path); return {'path':str(path)}
