from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import platform
from pathlib import Path
import time


def _digest(value: dict) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class ApplicationContext:
    captured_at: float
    platform: str
    available: bool
    application: str = ''
    executable: str = ''
    process_id: int | None = None
    process_start_token: str = ''
    window_id: str = ''
    window_title: str = ''
    source: str = 'unavailable'

    def safe_dict(self):
        data = asdict(self)
        data['executable'] = Path(self.executable).name if self.executable else ''
        identity = {'platform': data['platform'], 'application': data['application'], 'executable': data['executable'], 'process_id': data['process_id'], 'process_start_token': data['process_start_token'], 'window_id': data['window_id']}
        data['identity_digest'] = _digest(identity) if data['available'] else ''
        data['window_title_sha256'] = hashlib.sha256(data['window_title'].encode('utf-8')).hexdigest() if data['window_title'] else ''
        data.pop('window_title', None)
        return data


class ApplicationContextObserver:
    """On-demand foreground application/window identity; never polls or hooks."""

    def capture(self) -> dict:
        system = platform.system().lower() or 'unknown'
        if system != 'windows':
            return ApplicationContext(time.time(), system, False, source='unsupported_platform').safe_dict()
        value = self._windows()
        if value is None:
            return ApplicationContext(time.time(), 'windows', False, source='windows_identity_unavailable').safe_dict()
        return value.safe_dict()

    def _windows(self):
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32; kernel32 = ctypes.windll.kernel32
            hwnd = user32.GetForegroundWindow()
            if not hwnd: return None
            length = user32.GetWindowTextLengthW(hwnd); buf = ctypes.create_unicode_buffer(max(1, length + 1)); user32.GetWindowTextW(hwnd, buf, len(buf))
            pid = wintypes.DWORD(); user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not pid.value: return None
            executable = ''; start_token = ''; PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
            if handle:
                try:
                    size = wintypes.DWORD(32768); path = ctypes.create_unicode_buffer(size.value)
                    if kernel32.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)): executable = path.value
                    creation = wintypes.FILETIME(); exit_time = wintypes.FILETIME(); kernel = wintypes.FILETIME(); user = wintypes.FILETIME()
                    if kernel32.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_time), ctypes.byref(kernel), ctypes.byref(user)):
                        start_token = f'{creation.dwHighDateTime:08x}{creation.dwLowDateTime:08x}'
                finally:
                    kernel32.CloseHandle(handle)
            app = Path(executable).stem if executable else ''
            if not app: return None
            return ApplicationContext(captured_at=time.time(), platform='windows', available=True, application=app[:260], executable=executable, process_id=int(pid.value), process_start_token=start_token, window_id=f'hwnd:{int(hwnd):x}', window_title=buf.value[:1000], source='win32_foreground_window')
        except Exception:
            return None
