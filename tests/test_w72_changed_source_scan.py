from pathlib import Path
import re


def test_w72_changed_source_has_no_embedded_credentials():
    root=Path(__file__).resolve().parents[1]
    files=['browser/observation.py','browser/session.py','desktop/application_context.py','desktop/evidence_geometry.py','desktop/observation_policy.py','desktop/observation_policy_bridge.py','desktop/observation_policy_v72.py','desktop/operator_transactions.py','tools/advanced_control.py','tools/computer.py','vision/computer_intelligence.py','vision/screen_understanding.py']
    patterns=[re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),re.compile(r'\bAKIA[0-9A-Z]{16}\b'),re.compile(r'\bsk-[A-Za-z0-9_-]{24,}\b'),re.compile(r'(?i)(?:api[_-]?key|access[_-]?token|client[_-]?secret)\s*=\s*["\'][^"\']{16,}["\']')]
    findings=[]
    for rel in files:
        text=(root/rel).read_text(encoding='utf-8')
        for pattern in patterns:
            if pattern.search(text): findings.append((rel,pattern.pattern))
    assert findings==[]
