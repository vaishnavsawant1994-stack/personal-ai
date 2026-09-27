from __future__ import annotations
import argparse,json,sys
from pathlib import Path

REQUIRED={
    'v9_exact_head_ci':'Exact V9 candidate passed normal CI',
    'ios_simulator':'iOS simulator build/tests passed',
    'ios_physical_pairing':'Real iPhone paired with Personal AI and authenticated device channel passed',
    'ios_command_roundtrip':'Real iPhone returned correlated command results',
    'ios_revocation':'Revoked iPhone credential was rejected on reconnect',
    'apns_delivery':'Real APNs notification reached the configured iPhone',
    'realtime_audio':'Real microphone → OpenAI Realtime → speaker round trip passed',
    'reconnect_interruption':'Realtime interruption/reconnect evidence passed',
    'soak_1h':'1-hour reliability soak passed',
    'soak_4h':'4-hour reliability soak passed',
    'soak_6h':'6-hour reliability soak passed',
    'windows_authenticode':'Windows MSI Authenticode signature verified',
    'macos_developer_id':'macOS artifact Developer ID signature verified',
    'macos_notarized':'macOS notarization and staple verified',
    'release_manifest':'Ed25519 release manifest and installer hashes verified',
    'updater_install_rollback':'Updater install and rollback evidence passed',
    'security_audit':'Final security/permission attack suite passed',
    'memory_correctness':'Final memory correctness suite passed',
    'regression':'Complete regression suite passed',
}
OPTIONAL={'android_physical':'Physical Android evidence (deferred because owner currently uses iPhone and has no Android device)'}

def evaluate(evidence:dict):
    checks={key:bool(evidence.get(key,False)) for key in REQUIRED};optional={key:bool(evidence.get(key,False)) for key in OPTIONAL};missing=[key for key,ok in checks.items() if not ok]
    return {'production_ready':not missing,'required':checks,'optional':optional,'missing':missing}

def main():
    p=argparse.ArgumentParser();p.add_argument('evidence');p.add_argument('--json-output');p.add_argument('--strict',action='store_true');args=p.parse_args();path=Path(args.evidence);evidence=json.loads(path.read_text(encoding='utf-8'));result=evaluate(evidence);text=json.dumps(result,indent=2,sort_keys=True);print(text)
    if args.json_output:Path(args.json_output).write_text(text+'\n',encoding='utf-8')
    if args.strict and not result['production_ready']:return 2
    return 0
if __name__=='__main__':raise SystemExit(main())
