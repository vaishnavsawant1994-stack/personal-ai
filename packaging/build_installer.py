from __future__ import annotations
import os,platform,shutil,subprocess,tempfile
from pathlib import Path
def run(*cmd,cwd=None):subprocess.check_call(list(cmd),cwd=cwd)
def main():
    root=Path(__file__).resolve().parents[1];dist=root/'dist';run('pyinstaller','--clean',str(root/'packaging/personal_ai.spec'),cwd=root);system=platform.system()
    if system=='Darwin':
        if os.getenv('PERSONAL_AI_SKIP_DMG','').lower() in {'1','true','yes'}:return
        source=dist/'PersonalAI.app' if (dist/'PersonalAI.app').exists() else dist/'PersonalAI'
        run('hdiutil','create','-volname','Personal AI','-srcfolder',str(source),'-ov','-format','UDZO',str(dist/'PersonalAI.dmg'))
    elif system=='Windows':run('python',str(root/'packaging/setup_cxfreeze.py'),'bdist_msi',cwd=root)
    else:
        pkg=Path(tempfile.mkdtemp())/'personal-ai';(pkg/'DEBIAN').mkdir(parents=True);(pkg/'opt/personal-ai').mkdir(parents=True);shutil.copytree(dist/'PersonalAI',pkg/'opt/personal-ai/PersonalAI',dirs_exist_ok=True);(pkg/'usr/bin').mkdir(parents=True);launcher=pkg/'usr/bin/personal-ai';launcher.write_text('#!/bin/sh\nexec /opt/personal-ai/PersonalAI/PersonalAI "$@"\n');launcher.chmod(0o755);version=os.getenv('PERSONAL_AI_VERSION','0.5.0');(pkg/'DEBIAN/control').write_text(f'Package: personal-ai\nVersion: {version}\nSection: utils\nPriority: optional\nArchitecture: amd64\nMaintainer: Personal AI\nDescription: Personal AI desktop runtime\n');run('dpkg-deb','--build',str(pkg),str(dist/f'personal-ai_{version}_amd64.deb'))
if __name__=='__main__':main()
