from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json

@dataclass(frozen=True)
class PluginManifest:
    id:str
    name:str
    version:str
    description:str
    permissions:tuple[str,...]
    endpoint:str|None=None
    enabled:bool=False

class PluginManifestRegistry:
    """Declarative plugin catalogue. It never imports or executes arbitrary Python code."""
    def __init__(self,root:Path):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self._plugins={}
    def load(self):
        loaded={}
        for path in sorted(self.root.glob('*.json')):
            raw=json.loads(path.read_text(encoding='utf-8'))
            manifest=PluginManifest(
                id=str(raw['id']).strip(),name=str(raw.get('name',raw['id'])).strip(),version=str(raw.get('version','0.0.0')),
                description=str(raw.get('description','')),permissions=tuple(sorted(set(map(str,raw.get('permissions',[]))))),
                endpoint=str(raw['endpoint']).strip() if raw.get('endpoint') else None,enabled=bool(raw.get('enabled',False)))
            if not manifest.id or manifest.id in loaded:raise ValueError(f'invalid or duplicate plugin id: {manifest.id!r}')
            if manifest.endpoint and not manifest.endpoint.startswith('https://'):raise ValueError(f'plugin {manifest.id} endpoint must use HTTPS')
            loaded[manifest.id]=manifest
        self._plugins=loaded;return self.list()
    def list(self):return list(self._plugins.values())
    def get(self,plugin_id:str):return self._plugins[plugin_id]
