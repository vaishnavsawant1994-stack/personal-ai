from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import psutil

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))

from models.governed_router import GovernedModelRouter
from models.hybrid import HybridRequest, PrivacyMode, SafeContext
from models.router import ModelTimeout, ModelUnavailable


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


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--seconds',type=int,default=45); args=parser.parse_args()
    proc=psutil.Process(os.getpid()); start=proc.memory_info().rss; peak=start; deadline=time.time()+args.seconds
    router=GovernedModelRouter(settings()); iterations=0; local_ok=0; fallback_ok=0; privacy_blocks=0; timeouts=0; restarts=0; recoveries=0; circuit_opens=0
    while time.time()<deadline:
        mode=iterations%6
        if mode==0:
            breaker=router.observability.breakers['self_hosted']
            if breaker.state != 'closed':
                transition=router.observability.success('self_hosted',0.01)
                assert transition == 'closed' and breaker.state == 'closed'
                recoveries+=1
            assert router._run('chat',lambda provider:provider.id,hybrid_request=HybridRequest(privacy=PrivacyMode.LOCAL_ONLY))=='self_hosted'; local_ok+=1
        elif mode==1:
            def fail_local(provider):
                if provider.id=='self_hosted': raise ModelUnavailable(provider=provider.id)
                return provider.id
            assert router._run('chat',fail_local,hybrid_request=HybridRequest(privacy=PrivacyMode.EXTERNAL_ALLOWED))=='openai'; fallback_ok+=1
        elif mode==2:
            try:
                router._run('chat',lambda provider:(_ for _ in ()).throw(ModelUnavailable(provider=provider.id)),hybrid_request=HybridRequest(privacy=PrivacyMode.LOCAL_ONLY))
            except ModelUnavailable: privacy_blocks+=1
            else: raise AssertionError('LOCAL_ONLY unexpectedly fell back externally')
        elif mode==3:
            ctx=SafeContext.bounded(memory=['private'],knowledge=['private-k'],world=['safe-derived'],references=['observation:soak'])
            projected=ctx.external_projection(); assert not projected.memory and not projected.knowledge and projected.world==('safe-derived',)
        elif mode==4:
            def timeout_local(provider):
                if provider.id=='self_hosted': raise ModelTimeout(provider=provider.id)
                return 'ok'
            assert router._run('chat',timeout_local,hybrid_request=HybridRequest(privacy=PrivacyMode.EXTERNAL_ALLOWED))=='ok'; timeouts+=1
            if router.observability.breakers['self_hosted'].state == 'open': circuit_opens+=1
        else:
            try:
                router._run('vision',lambda provider:'never',hybrid_request=HybridRequest(capability='vision',privacy=PrivacyMode.EXTERNAL_ALLOWED,blocked_providers=('self_hosted','openai','openrouter','gemini')))
            except ModelUnavailable: pass
            else: raise AssertionError('blocked capability route unexpectedly succeeded')
        if iterations and iterations%500==0:
            router=GovernedModelRouter(settings()); restarts+=1
        assert len(router.observability.generations)<=200
        peak=max(peak,proc.memory_info().rss); iterations+=1
    end=proc.memory_info().rss
    if not circuit_opens or not recoveries: raise SystemExit('P9 soak did not exercise circuit-open and recovery transitions')
    if end-start>128*1024*1024: raise SystemExit(f'P9 memory growth too high: {end-start}')
    print({'p9_iterations':iterations,'rss_start':start,'rss_peak':peak,'rss_end':end,'rss_growth':end-start,'local_ok':local_ok,'fallback_ok':fallback_ok,'privacy_blocks':privacy_blocks,'timeouts':timeouts,'circuit_opens':circuit_opens,'recoveries':recoveries,'restarts':restarts,'history_size':len(router.observability.generations)})


if __name__=='__main__': main()
