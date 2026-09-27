# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys
ROOT=Path(SPECPATH).resolve().parent
a=Analysis([str(ROOT/'app/main.py')],pathex=[str(ROOT)],binaries=[],datas=[],hiddenimports=['keyring.backends','uvicorn.logging','uvicorn.loops.auto','uvicorn.protocols.http.auto','uvicorn.protocols.websockets.auto'],hookspath=[],hooksconfig={},runtime_hooks=[],excludes=[],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='PersonalAI',debug=False,bootloader_ignore_signals=False,strip=False,upx=False,console=False)
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,upx_exclude=[],name='PersonalAI')
if sys.platform=='darwin':
    app=BUNDLE(coll,name='PersonalAI.app',bundle_identifier='ai.personal.desktop',info_plist={'CFBundleDisplayName':'Personal AI','NSHighResolutionCapable':True})
