from __future__ import annotations

from dataclasses import dataclass
import platform
from typing import Protocol, Any

from security.policy_targets import classify_clipboard


class ClipboardAdapter(Protocol):
    def read_text(self) -> tuple[str,int]: ...
    def write_text(self,text:str) -> int: ...
    def clear(self) -> int: ...


class UnsupportedClipboardAdapter:
    def _unsupported(self,*args,**kwargs): raise RuntimeError('unsupported_platform')
    read_text=_unsupported;write_text=_unsupported;clear=_unsupported


class MemoryClipboardAdapter:
    def __init__(self,text=''):self._text=str(text);self._seq=1
    def read_text(self):return self._text,self._seq
    def write_text(self,text):self._text=str(text);self._seq+=1;return self._seq
    def clear(self):self._text='';self._seq+=1;return self._seq


class WindowsClipboardAdapter:
    """On-demand Windows text clipboard access. No hooks, polling, history, or background monitoring."""
    CF_UNICODETEXT=13;GMEM_MOVEABLE=0x0002
    @staticmethod
    def _seq():
        import ctypes
        return int(ctypes.windll.user32.GetClipboardSequenceNumber())
    def read_text(self):
        import ctypes
        user32=ctypes.windll.user32;kernel32=ctypes.windll.kernel32
        if not user32.OpenClipboard(None):raise RuntimeError('clipboard_blocked')
        try:
            handle=user32.GetClipboardData(self.CF_UNICODETEXT)
            if not handle:return '',self._seq()
            ptr=kernel32.GlobalLock(handle)
            if not ptr:raise RuntimeError('clipboard_blocked')
            try:text=ctypes.wstring_at(ptr)
            finally:kernel32.GlobalUnlock(handle)
            return text,self._seq()
        finally:user32.CloseClipboard()
    def write_text(self,text):
        import ctypes
        user32=ctypes.windll.user32;kernel32=ctypes.windll.kernel32;value=str(text);raw=(value+'\x00').encode('utf-16-le')
        if not user32.OpenClipboard(None):raise RuntimeError('clipboard_blocked')
        handle=None
        try:
            if not user32.EmptyClipboard():raise RuntimeError('clipboard_blocked')
            handle=kernel32.GlobalAlloc(self.GMEM_MOVEABLE,len(raw))
            if not handle:raise MemoryError('clipboard_blocked')
            ptr=kernel32.GlobalLock(handle)
            if not ptr:raise RuntimeError('clipboard_blocked')
            try:ctypes.memmove(ptr,raw,len(raw))
            finally:kernel32.GlobalUnlock(handle)
            if not user32.SetClipboardData(self.CF_UNICODETEXT,handle):raise RuntimeError('clipboard_blocked')
            handle=None
            return self._seq()
        finally:
            user32.CloseClipboard()
            if handle:kernel32.GlobalFree(handle)
    def clear(self):
        import ctypes
        user32=ctypes.windll.user32
        if not user32.OpenClipboard(None):raise RuntimeError('clipboard_blocked')
        try:
            if not user32.EmptyClipboard():raise RuntimeError('clipboard_blocked')
            return self._seq()
        finally:user32.CloseClipboard()


@dataclass(frozen=True)
class ClipboardSnapshot:
    sequence:int;sha256:str;classification:str;size:int;secret:bool
    @classmethod
    def from_value(cls,text:str,sequence:int,max_bytes:int=64*1024):
        meta=classify_clipboard(text,max_bytes=max_bytes);return cls(int(sequence),meta['sha256'],meta['classification'],int(meta['size']),bool(meta['secret']))
    def safe_dict(self)->dict[str,Any]:return {'sequence':self.sequence,'sha256':self.sha256,'classification':self.classification,'size':self.size,'secret':self.secret}


SAFE_HOTKEYS={('ctrl','a'),('ctrl','c'),('ctrl','v'),('ctrl','x'),('ctrl','z'),('ctrl','y'),('ctrl','f'),('ctrl','s'),('ctrl','p'),('alt','left'),('alt','right'),('esc',),('enter',),('tab',),('shift','tab')}
def validate_hotkey(keys:list[str]|tuple[str,...])->tuple[str,...]:
    normalized=tuple(str(k).strip().lower() for k in keys if str(k).strip())
    if normalized not in SAFE_HOTKEYS:raise PermissionError('keyboard_shortcut_not_allowed')
    return normalized

def default_clipboard_adapter()->ClipboardAdapter:
    return WindowsClipboardAdapter() if platform.system().lower()=='windows' else UnsupportedClipboardAdapter()
