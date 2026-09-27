from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1] / 'web-companion'

def test_web_companion_required_files():
    for name in ('index.html','styles.css','app.js','manifest.webmanifest','sw.js','vercel.json'):
        assert (ROOT / name).is_file()

def test_web_companion_does_not_embed_privileged_credentials():
    text='\n'.join(p.read_text(encoding='utf-8') for p in ROOT.iterdir() if p.is_file()).lower()
    forbidden=('openai_api_key','authorization: bearer','apns_private_key','client_secret','private_key_b64','device_bearer_token')
    assert not any(item in text for item in forbidden)

def test_vercel_security_headers_and_no_external_connect():
    config=json.loads((ROOT/'vercel.json').read_text(encoding='utf-8'))
    headers={h['key']:h['value'] for rule in config['headers'] for h in rule['headers']}
    assert headers['X-Content-Type-Options']=='nosniff'
    assert "connect-src 'self'" in headers['Content-Security-Policy']
    assert "frame-ancestors 'none'" in headers['Content-Security-Policy']

def test_manifest_is_standalone():
    manifest=json.loads((ROOT/'manifest.webmanifest').read_text(encoding='utf-8'))
    assert manifest['display']=='standalone'
    assert manifest['start_url']=='/'
