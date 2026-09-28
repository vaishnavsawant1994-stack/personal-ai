from __future__ import annotations
from fastapi import APIRouter
from fastapi.responses import HTMLResponse


def connector_oauth_callback_router():
    router=APIRouter(tags=['connectors'])
    @router.get('/connector-oauth/callback',response_class=HTMLResponse)
    def connector_oauth_callback():
        html="""<!doctype html><meta charset=\"utf-8\"><meta name=\"referrer\" content=\"no-referrer\"><title>Personal AI connector</title><body><p id=\"s\">Completing secure account connection…</p><script>
const q=new URLSearchParams(location.search),state=q.get('state'),code=q.get('code');history.replaceState(null,'',location.pathname);
(async()=>{const el=document.getElementById('s');if(!state||!code){el.textContent='Account connection could not be completed.';return;}try{const r=await fetch('/iphone/api/connectors/oauth/finalize',{method:'POST',credentials:'same-origin',headers:{'content-type':'application/json'},body:JSON.stringify({state,code})});el.textContent=r.ok?'Account connected. You can close this window.':'Account connection was rejected. Return to Personal AI and try again.';}catch(_){el.textContent='Account connection could not be completed. Return to Personal AI and try again.';}})();
</script></body>"""
        return HTMLResponse(html,headers={'Cache-Control':'no-store','Pragma':'no-cache','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'; script-src 'unsafe-inline'; connect-src 'self'; style-src 'none'; base-uri 'none'; frame-ancestors 'none'"})
    return router
