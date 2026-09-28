from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import platform
import subprocess
import time
from typing import Any, Protocol

from security.policy_targets import TargetValidationError, application_identity


@dataclass(frozen=True)
class WindowIdentity:
    process_id: int
    executable: str
    executable_sha256: str
    window_id: str
    title_digest: str
    foreground: bool
    visible: bool = True
    enabled: bool = True

    def safe_dict(self) -> dict[str, Any]:
        return {'process_id':int(self.process_id),'executable':Path(self.executable).name if self.executable else '','executable_sha256':self.executable_sha256,'window_id':self.window_id,'title_digest':self.title_digest,'foreground':bool(self.foreground),'visible':bool(self.visible),'enabled':bool(self.enabled)}


class DesktopPlatformAdapter(Protocol):
    platform_name: str
    def application_identity(self, executable: str) -> dict[str, Any]: ...
    def launch(self, executable: str, args: list[str]) -> dict[str, Any]: ...
    def foreground_window(self) -> WindowIdentity | None: ...
    def find_window_for_process(self, process_id: int, timeout_seconds: float = 3.0) -> WindowIdentity | None: ...
    def control_state(self, target_id: str) -> dict[str, Any] | None: ...
    def focus_window(self, window_id: str) -> bool: ...
    def window_action(self, window_id: str, action: str, **kwargs) -> bool: ...
    def input_click(self, x: int, y: int, *, button: str = 'left') -> None: ...
    def input_type(self, text: str) -> None: ...
    def input_select(self, target_id: str, option: str) -> None: ...
    def input_hotkey(self, keys: tuple[str, ...]) -> None: ...
    def input_scroll(self, amount: int) -> None: ...
    def release_input(self) -> None: ...
    def read_visible_text(self, window_id: str, *, max_chars: int = 12000) -> str: ...


class UnsupportedDesktopAdapter:
    platform_name='unsupported'
    def _unsupported(self,*args,**kwargs): raise RuntimeError('unsupported_platform')
    application_identity=_unsupported;launch=_unsupported;foreground_window=_unsupported;find_window_for_process=_unsupported;control_state=_unsupported;focus_window=_unsupported;window_action=_unsupported;input_click=_unsupported;input_type=_unsupported;input_select=_unsupported;input_hotkey=_unsupported;input_scroll=_unsupported;release_input=_unsupported;read_visible_text=_unsupported


class WindowsDesktopAdapter:
    """Bounded Win32 adapter. It never invokes a shell and never resolves executable names through PATH."""
    platform_name='windows'
    _WINDOW_ACTIONS={'minimize','maximize','restore','close','move_resize'}

    def application_identity(self, executable: str) -> dict[str, Any]:
        raw=str(executable or '').strip()
        if not raw or not Path(raw).is_absolute(): raise TargetValidationError('application_not_allowed','Executable must be an absolute canonical path.')
        return application_identity(raw)

    def launch(self, executable: str, args: list[str]) -> dict[str, Any]:
        identity=self.application_identity(executable);safe_args=self._validate_args(args)
        proc=subprocess.Popen([identity['canonical_path'],*safe_args],shell=False,close_fds=True)
        window=self.find_window_for_process(proc.pid,3.0)
        return {'process_id':int(proc.pid),'application':identity,'window':window.safe_dict() if window else None}

    @staticmethod
    def _validate_args(args:list[str])->list[str]:
        if not isinstance(args,list):raise ValueError('application arguments must be a list')
        if len(args)>32:raise ValueError('too many application arguments')
        out=[]
        for value in args:
            text=str(value)
            if len(text)>2048 or any(x in text for x in ('\x00','\r','\n')):raise ValueError('invalid application argument')
            out.append(text)
        return out

    @staticmethod
    def _hwnd(value:str)->int:
        text=str(value or '')
        if not text.startswith('hwnd:'):raise ValueError('invalid window identity')
        return int(text.split(':',1)[1],16)

    def _window_identity(self, hwnd:int, *, foreground:bool)->WindowIdentity|None:
        try:
            import ctypes
            from ctypes import wintypes
            user32=ctypes.windll.user32;kernel32=ctypes.windll.kernel32
            pid=wintypes.DWORD();user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
            if not pid.value:return None
            handle=kernel32.OpenProcess(0x1000,False,pid.value)
            if not handle:return None
            executable=''
            try:
                size=wintypes.DWORD(32768);buf=ctypes.create_unicode_buffer(size.value)
                if kernel32.QueryFullProcessImageNameW(handle,0,buf,ctypes.byref(size)):executable=buf.value
            finally:kernel32.CloseHandle(handle)
            if not executable:return None
            identity=application_identity(executable);length=user32.GetWindowTextLengthW(hwnd);title=ctypes.create_unicode_buffer(max(1,length+1));user32.GetWindowTextW(hwnd,title,len(title))
            return WindowIdentity(int(pid.value),identity['canonical_path'],identity['sha256'],f'hwnd:{int(hwnd):x}',hashlib.sha256(title.value.encode()).hexdigest(),foreground,bool(user32.IsWindowVisible(hwnd)),bool(user32.IsWindowEnabled(hwnd)))
        except Exception:return None

    def foreground_window(self)->WindowIdentity|None:
        try:
            import ctypes
            hwnd=ctypes.windll.user32.GetForegroundWindow()
            return self._window_identity(int(hwnd),foreground=True) if hwnd else None
        except Exception:return None

    def find_window_for_process(self,process_id:int,timeout_seconds:float=3.0)->WindowIdentity|None:
        deadline=time.monotonic()+max(0,min(float(timeout_seconds),3.0))
        while True:
            try:
                import ctypes
                from ctypes import wintypes
                found=[]
                CALLBACK=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
                def visit(hwnd,lparam):
                    pid=wintypes.DWORD();ctypes.windll.user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
                    if int(pid.value)==int(process_id) and ctypes.windll.user32.IsWindowVisible(hwnd):found.append(int(hwnd));return False
                    return True
                ctypes.windll.user32.EnumWindows(CALLBACK(visit),0)
                if found:return self._window_identity(found[0],foreground=False)
            except Exception:return None
            if time.monotonic()>=deadline:return None
            time.sleep(.05)

    def control_state(self,target_id:str)->dict[str,Any]|None:
        # No dependency is allowed to fabricate UIA identity. A future qualified UIA provider can implement this protocol.
        return None

    def focus_window(self,window_id:str)->bool:
        import ctypes
        return bool(ctypes.windll.user32.SetForegroundWindow(self._hwnd(window_id)))

    def window_action(self,window_id:str,action:str,**kwargs)->bool:
        if action not in self._WINDOW_ACTIONS:raise ValueError('window action not allowed')
        import ctypes
        user32=ctypes.windll.user32;hwnd=self._hwnd(window_id)
        if action=='close':return bool(user32.PostMessageW(hwnd,0x0010,0,0))
        if action=='move_resize':
            x,y,width,height=(kwargs.get(k) for k in ('x','y','width','height'))
            if None in (x,y,width,height) or int(width)<=0 or int(height)<=0:raise ValueError('invalid window geometry')
            return bool(user32.MoveWindow(hwnd,int(x),int(y),int(width),int(height),True))
        return bool(user32.ShowWindow(hwnd,{'minimize':6,'maximize':3,'restore':9}[action]))

    @staticmethod
    def _pg():
        import pyautogui
        pyautogui.FAILSAFE=True
        return pyautogui
    def input_click(self,x:int,y:int,*,button='left')->None:self._pg().click(x=int(x),y=int(y),button=button)
    def input_type(self,text:str)->None:self._pg().write(str(text),interval=.01)
    def input_select(self,target_id:str,option:str)->None:raise RuntimeError('target_changed')
    def input_hotkey(self,keys:tuple[str,...])->None:self._pg().hotkey(*keys)
    def input_scroll(self,amount:int)->None:self._pg().scroll(int(amount))
    def release_input(self)->None:
        pg=self._pg()
        for key in ('ctrl','shift','alt','win'):
            try:pg.keyUp(key)
            except Exception:pass
        for button in ('left','middle','right'):
            try:pg.mouseUp(button=button)
            except Exception:pass
    def read_visible_text(self,window_id:str,*,max_chars:int=12000)->str:return ''


def default_desktop_adapter()->DesktopPlatformAdapter:
    return WindowsDesktopAdapter() if platform.system().lower()=='windows' else UnsupportedDesktopAdapter()
