from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import time
import tracemalloc
from types import SimpleNamespace

from models.governed_router import GovernedModelRouter
from models.hybrid import HybridPolicy, HybridRequest, PrivacyMode, SafeContext
from recovery.backup import BACKUP_MAGIC, BackupService


class FixedKeyStore:
    def get_or_create(self):
        return b'9' * 32


def settings():
    return SimpleNamespace(
        ai_provider='self_hosted', local_ai_explicit=True, hosted_runtime=False, cloud_runtime_enabled=False,
        self_hosted_ai_url='http://127.0.0.1:11434/v1', self_hosted_ai_api_key='', self_hosted_ai_model='local',
        local_ai_url='http://127.0.0.1:11434/v1', local_ai_model='local', openrouter_api_key='', openrouter_model='',
        openai_api_key='test', openai_base_url='https://example.invalid/v1', openai_model='external',
        gemini_api_key='', gemini_base_url='https://example.invalid/v1', gemini_model='',
        model_fallback_providers=('openai',), model_disabled_providers=(), model_allowed_providers=(), model_privacy_mode='local_preferred',
        model_request_timeout_seconds=1, model_health_timeout_seconds=1, model_retry_attempts=0, model_retry_backoff_seconds=0,
        model_max_failovers=3, model_local_first=True, allow_external_for_sensitive=False,
    )


def test_p9_observability_history_is_bounded():
    r=GovernedModelRouter(settings())
    req=HybridRequest(privacy=PrivacyMode.LOCAL_ONLY)
    for _ in range(500): r._run('chat',lambda provider:'ok',hybrid_request=req)
    snap=r.observability.snapshot()
    assert len(r.observability.generations) <= 200
    assert len(snap['recent_generations']) <= 25


def test_p9_concurrent_routing_isolation_and_no_deadlock():
    def one(i):
        r=GovernedModelRouter(settings())
        req=HybridRequest(privacy=PrivacyMode.LOCAL_ONLY if i%2==0 else PrivacyMode.EXTERNAL_ALLOWED)
        return r._run('chat',lambda provider:provider.id,hybrid_request=req)
    with ThreadPoolExecutor(max_workers=16) as pool:
        results=list(pool.map(one,range(128)))
    assert len(results)==128 and set(results)=={'self_hosted'}


def test_p9_restart_rebuilds_policy_without_restoring_runtime_authority():
    first=GovernedModelRouter(settings())
    first.observability.breakers['self_hosted'].state='open'
    restarted=GovernedModelRouter(settings())
    assert restarted.observability.breakers['self_hosted'].state == 'closed'
    assert restarted.status()['p9']['model_output_authority'] is False


def test_p9_encrypted_backup_restore_contains_no_runtime_credentials(tmp_path):
    source=tmp_path/'source'; target=tmp_path/'target'; source.mkdir(); target.mkdir()
    (source/'hybrid-policy.json').write_text(json.dumps({'privacy':'local_preferred','allowed_providers':['self_hosted','openai']}),encoding='utf-8')
    archive=BackupService(source,root_key_store=FixedKeyStore()).create('p9-state.paibackup')
    raw=archive.read_bytes()
    assert raw.startswith(BACKUP_MAGIC)
    assert b'test-api-key' not in raw and b'Authorization' not in raw
    manifest=BackupService(source,root_key_store=FixedKeyStore()).inspect(archive)
    assert manifest['encrypted'] is True
    restored=BackupService(target,root_key_store=FixedKeyStore()).restore(archive)
    assert restored['ok'] is True and restored['encrypted'] is True
    assert json.loads((target/'hybrid-policy.json').read_text(encoding='utf-8'))['privacy']=='local_preferred'


def test_p9_context_and_memory_are_bounded():
    tracemalloc.start()
    ctx=SafeContext.bounded(memory=['m'*5000 for _ in range(100)],knowledge=['k'*5000 for _ in range(100)],world=['w'*5000 for _ in range(100)],references=['r'*5000 for _ in range(100)])
    _,peak=tracemalloc.get_traced_memory(); tracemalloc.stop()
    assert all(len(group) <= 8 for group in (ctx.memory,ctx.knowledge,ctx.world,ctx.references))
    assert all(len(item) <= 2000 for group in (ctx.memory,ctx.knowledge,ctx.world,ctx.references) for item in group)
    assert peak < 32*1024*1024


def test_p9_performance_envelope_is_bounded_and_reported():
    r=GovernedModelRouter(settings())
    local=r.providers['self_hosted']; external=r.providers['openai']
    req_local=HybridRequest(privacy=PrivacyMode.LOCAL_ONLY)
    req_external=HybridRequest(privacy=PrivacyMode.EXTERNAL_ALLOWED)
    started=time.perf_counter()
    for _ in range(5000): HybridPolicy.filter_candidates(req_local,[external,local])
    policy_seconds=time.perf_counter()-started
    started=time.perf_counter()
    for _ in range(1000): r._eligible('chat','internal',hybrid_request=req_external)
    health_selection_seconds=time.perf_counter()-started
    started=time.perf_counter()
    for _ in range(500): r._run('chat',lambda provider:'ok',hybrid_request=req_local)
    route_seconds=time.perf_counter()-started
    restarted_started=time.perf_counter(); GovernedModelRouter(settings()); restart_seconds=time.perf_counter()-restarted_started
    metrics={'policy_5000_seconds':round(policy_seconds,6),'health_selection_1000_seconds':round(health_selection_seconds,6),'route_500_seconds':round(route_seconds,6),'restart_seconds':round(restart_seconds,6),'history_size':len(r.observability.generations)}
    assert policy_seconds < 5 and health_selection_seconds < 5 and route_seconds < 5 and restart_seconds < 1
    assert metrics['history_size'] <= 200
    print('P9_PERFORMANCE_RESULTS='+json.dumps(metrics,sort_keys=True),flush=True)
