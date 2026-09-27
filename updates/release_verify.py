from __future__ import annotations
import argparse,base64,hashlib,json
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

def sha256(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def verify(manifest_path,signature_path,public_key_b64,artifact_dir=None):
    manifest_path=Path(manifest_path);signature_path=Path(signature_path);raw=manifest_path.read_bytes();sig=base64.b64decode(signature_path.read_text().strip());key=Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64));key.verify(sig,raw);manifest=json.loads(raw)
    root=Path(artifact_dir) if artifact_dir else manifest_path.parent
    for item in manifest.get('artifacts',[]):
        path=root/item['name']
        if not path.is_file():raise FileNotFoundError(path)
        if path.stat().st_size!=item['size']:raise ValueError(f"size mismatch for {path.name}")
        if sha256(path)!=item['sha256']:raise ValueError(f"sha256 mismatch for {path.name}")
    return manifest

def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',required=True);p.add_argument('--signature',required=True);p.add_argument('--public-key-b64',required=True);p.add_argument('--artifact-dir');a=p.parse_args();m=verify(a.manifest,a.signature,a.public_key_b64,a.artifact_dir);print(json.dumps({'ok':True,'version':m.get('version'),'artifacts':len(m.get('artifacts',[]))},sort_keys=True))
if __name__=='__main__':main()
