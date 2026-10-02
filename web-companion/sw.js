const CACHE='personal-ai-web-v13';
const ASSETS=['/','/index.html','/design-system.css','/styles.css','/app.js','/manifest.webmanifest'];
self.addEventListener('install',event=>{self.skipWaiting();event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(ASSETS)))});
self.addEventListener('activate',event=>event.waitUntil(Promise.all([self.clients.claim(),caches.keys().then(keys=>Promise.all(keys.filter(key=>key!==CACHE).map(key=>caches.delete(key))))])));
self.addEventListener('fetch',event=>{
 const url=new URL(event.request.url);
 if(event.request.method!=='GET'||url.origin!==self.location.origin||(!ASSETS.includes(url.pathname)&&event.request.mode!=='navigate'))return;
 event.respondWith(fetch(event.request).then(response=>{
  if(response.ok&&ASSETS.includes(url.pathname)){const copy=response.clone();event.waitUntil(caches.open(CACHE).then(cache=>cache.put(event.request,copy)))}
  return response;
 }).catch(async()=>await caches.match(event.request)||(event.request.mode==='navigate'?await caches.match('/index.html'):new Response('Unavailable offline',{status:503,headers:{'Content-Type':'text/plain'}}))));
});
