from __future__ import annotations
import argparse,base64,hashlib,json,os
from datetime import datetime,timezone
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

def sha256(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('--version',required=True);p.add_argument('--output',required=True);p.add_argument('artifacts',nargs='+');a=p.parse_args();key_b64=os.environ.get('PERSONAL_AI_RELEASE_PRIVATE_KEY_B64','').strip()
    if not key_b64:raise SystemExit('PERSONAL_AI_RELEASE_PRIVATE_KEY_B64 is required')
    raw_key=base64.b64decode(key_b64)
    if len(raw_key)!=32:raise SystemExit('release signing key must decode to exactly 32 bytes')
    key=Ed25519PrivateKey.from_private_bytes(raw_key);artifacts=[Path(x) for x in a.artifacts]
    if not artifacts or any(not x.is_file() for x in artifacts):raise SystemExit('all release artifacts must exist before signing')
    manifest={'schema':1,'version':a.version,'created_at':datetime.now(timezone.utc).isoformat(),'artifacts':[{'name':x.name,'sha256':sha256(x),'size':x.stat().st_size} for x in artifacts]};raw=json.dumps(manifest,sort_keys=True,separators=(',',':')).encode();out=Path(a.output);out.write_bytes(raw);out.with_suffix(out.suffix+'.sig').write_text(base64.b64encode(key.sign(raw)).decode())
if __name__=='__main__':main()
