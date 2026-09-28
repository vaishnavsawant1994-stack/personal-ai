from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse


def capability_console_router(runtime):
    router = APIRouter(prefix='/capabilities', tags=['capability-console'])

    @router.get('/api/status')
    def status():
        future = runtime.get('future_intelligence')
        phases = future.status() if future is not None else {}
        return {
            'product': 'Personal AI',
            'surface': 'P4-P10 Capability Console',
            'runtime_ready': future is not None,
            'p3_qualification_present': runtime.get('p3_qualification') is not None,
            'voice_qualification_present': runtime.get('voice_qualification') is not None,
            'second_brain_present': runtime.get('second_brain') is not None,
            'continuity_present': runtime.get('continuity') is not None,
            'automation_present': runtime.get('automations') is not None,
            'proactive_present': runtime.get('proactive') is not None,
            'phases': phases,
            'qualification_notice': 'Implementation status is not real-device or production qualification evidence.',
        }

    @router.get('', response_class=HTMLResponse, include_in_schema=False)
    @router.get('/', response_class=HTMLResponse, include_in_schema=False)
    def page():
        return HTMLResponse(_PAGE, headers={'Cache-Control': 'no-store'})

    return router


_PAGE = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#07090d"><title>Personal AI · Capability Console</title>
<style>
:root{color-scheme:dark;font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display",Inter,sans-serif;background:#07090d;color:#f5f7fb}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 50% 15%,#172033 0,#090c12 38%,#050609 100%);min-height:100dvh}
main{max-width:900px;margin:auto;padding:max(22px,env(safe-area-inset-top)) 18px max(30px,env(safe-area-inset-bottom))}
header{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-bottom:28px}.brand{font-weight:750}.pill{border:1px solid #303849;border-radius:999px;padding:7px 10px;font-size:12px;color:#bec8da}
h1{font-size:32px;line-height:1.05;margin:12px 0 8px}.sub{color:#9ba6b8;line-height:1.45;margin:0 0 24px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}.card{background:rgba(16,21,31,.78);border:1px solid #252d3b;border-radius:20px;padding:18px;min-height:160px;backdrop-filter:blur(18px)}
.top{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}.phase{font-weight:750;font-size:18px}.state{font-size:11px;border-radius:999px;padding:5px 8px;border:1px solid #35415a;color:#ccd5e4;max-width:120px;text-align:right}.ok{border-color:#285d47;color:#aee6c8}.locked{border-color:#64464f;color:#edbdc7}.desc{color:#9ca8bb;font-size:13px;line-height:1.45;margin-top:14px}.foundation{display:flex;flex-wrap:wrap;gap:7px;margin-top:14px}.chip{font-size:11px;padding:5px 7px;border-radius:999px;background:#101724;border:1px solid #263248;color:#aebbd0}.footer{margin-top:20px;padding:16px;border:1px solid #252d3b;border-radius:18px;color:#8f9bad;font-size:12px;line-height:1.5}.dot{width:8px;height:8px;border-radius:50%;display:inline-block;background:#73d7a5;box-shadow:0 0 12px #73d7a5;margin-right:7px}
</style></head><body><main>
<header><div class="brand">Personal AI</div><div class="pill"><span class="dot"></span><span id="runtime">Checking runtime</span></div></header>
<h1>Capability Console</h1><p class="sub">Live read-only view of the P4–P10 software foundations and their qualification locks. This console never grants authority or marks a phase qualified.</p>
<div id="grid" class="grid"></div>
<div class="footer" id="footer">Loading implementation status…</div>
<script>
const descriptions={p4:'Everyday Personal Intelligence · briefing, goals, reminders, follow-ups, attention and context.',p5:'Deep Second Brain · Life Graph, timeline, causal relationships and evidence-backed decision context.',p6:'Autonomous Personal Operations · long-horizon plans with governed approval boundaries.',p7:'Multimodal World Understanding · screen, camera, image, document, audio, location, sensors and wearables.',p8:'Personal AI Everywhere · unified identity and continuity across device surfaces.',p9:'Sovereign / Hybrid Intelligence · privacy-aware local, private and cloud model routing.',p10:'Advanced Autonomous Intelligence · agents, long-horizon planning, evaluation, learning and strategy.'};
const names={p4:'P4 · Everyday Intelligence',p5:'P5 · Deep Second Brain',p6:'P6 · Personal Operations',p7:'P7 · World Understanding',p8:'P8 · Everywhere',p9:'P9 · Hybrid Intelligence',p10:'P10 · Advanced Intelligence'};
async function load(){try{const r=await fetch('/capabilities/api/status',{cache:'no-store'});const d=await r.json();document.getElementById('runtime').textContent=d.runtime_ready?'Runtime online':'Runtime unavailable';const g=document.getElementById('grid');g.innerHTML='';for(const key of ['p4','p5','p6','p7','p8','p9','p10']){const p=d.phases[key]||{};const active=String(p.activation||'').toLowerCase()==='safe-now';const el=document.createElement('article');el.className='card';el.innerHTML=`<div class="top"><div class="phase">${names[key]}</div><div class="state ${active?'ok':'locked'}">${active?'SAFE NOW':'GATED'}</div></div><div class="desc">${descriptions[key]}</div><div class="foundation"><span class="chip">Implemented: ${p.implemented===true?'yes':'no'}</span><span class="chip">${p.activation||'status unavailable'}</span></div>`;g.appendChild(el)}document.getElementById('footer').textContent=d.qualification_notice+' · P3 recorder: '+(d.p3_qualification_present?'present':'missing')+' · Second Brain: '+(d.second_brain_present?'present':'missing')+' · Continuity: '+(d.continuity_present?'present':'missing')+' · Automation: '+(d.automation_present?'present':'missing');}catch(e){document.getElementById('runtime').textContent='Unavailable';document.getElementById('footer').textContent='Could not read runtime status: '+e.message}}
load();setInterval(load,15000);
</script></main></body></html>'''
