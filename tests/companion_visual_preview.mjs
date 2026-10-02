import assert from 'node:assert/strict';
import {chromium,firefox,webkit} from 'playwright';
const engine=process.env.PERSONAL_AI_BROWSER || 'chromium';
assert.ok(['chromium','firefox','webkit'].includes(engine),'supported browser engine');
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const executablePath=process.env.PERSONAL_AI_BROWSER_EXECUTABLE || (engine==="chromium"?process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE:undefined);
const browser=await ({chromium,firefox,webkit})[engine].launch({headless:true,...(executablePath?{executablePath}:{})});
try {
 const page=await browser.newPage({viewport:{width:390,height:844},serviceWorkers:"block"}),errors=[];let emergencyCalls=0;
 page.on('pageerror',error=>errors.push(error.message));
 await page.route('https://runtime.example/**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path==='/cloud/emergency-stop')emergencyCalls++;
  const body=path==='/pair/confirm'?{device:{id:'qa-companion'},bearer_token:'qa-token'}:path==='/cloud/session'?{session_token:'qa-session',expires_at:Date.now()/1000+3600}:path==='/cloud/status'?{state:'ready'}:path==='/cloud/command'?{reply:'Your conversation is connected.'}:path==='/cloud/memory/search'?{results:[{subject:'Project planning',content:'Verified companion memory search.'}]}:{};
  return route.fulfill({status:200,contentType:'application/json',headers:{'Access-Control-Allow-Origin':'*'},body:JSON.stringify(body)});
 });
 await page.goto('http://127.0.0.1:4175/');
 await page.addScriptTag({path:process.env.PERSONAL_AI_AXE_PATH||require.resolve('axe-core/axe.min.js')});
 for(const [width,height] of [[320,568],[360,800],[375,812],[390,844],[393,852],[430,932],[768,1024],[820,1180],[1024,768],[1280,800],[1440,900]]){
  await page.setViewportSize({width,height});
  for(const name of ['home','memory','control','dashboard']){
   await page.click(`nav button[data-page="${name}"]`);
   assert.ok(await page.locator(`#${name}`).isVisible());
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),name+' overflow at '+width);
   if(width===390){const violations=await page.evaluate(async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa']}})).violations.map(v=>({id:v.id,targets:v.nodes.map(n=>n.target)})));assert.deepEqual(violations,[],name+' accessibility');}
   if([320,390,820,1440].includes(width))await page.screenshot({path:`artifacts/companion-${name}-${width}x${height}.png`,fullPage:true});
  }
 }
 await page.click('nav button[data-page="control"]');
 await page.fill('#runtime-origin','https://runtime.example');await page.fill('#pair-token','qa-token');await page.fill('#pair-code','123456');await page.click('#pair button');
 await page.waitForFunction(()=>document.querySelector('#pair-message').textContent.includes('Paired securely'));
 assert.equal(await page.locator('#pair-token').inputValue(),'');
 await page.click('nav button[data-page="home"]');await page.fill('#prompt','Hello');await page.click('#ask button');
 await page.waitForFunction(()=>document.querySelector('#reply').textContent==='Your conversation is connected.');
 await page.click('nav button[data-page="memory"]');await page.fill('#memory-query','Project');await page.click('#memory-search button');
 await page.waitForFunction(()=>document.querySelector('#memory-results').textContent.includes('Verified companion memory search.'));
 await page.click('nav button[data-page="control"]');
 await page.click('#resume');await page.waitForSelector('#companionDialog[open]');
 await page.click('#companionDialog [value="cancel"]');assert.equal(emergencyCalls,0,'cancelled resume must not change runtime state');
 await page.fill('#owner-secret','qa-owner');await page.click('#resume');await page.click('#companionDialog [value="continue"]');
 await page.waitForFunction(()=>document.querySelector('#owner-secret').value==='');assert.equal(emergencyCalls,1,'confirmed resume uses the existing owner endpoint once');
 assert.deepEqual(errors,[]);
 console.log('Companion: four surfaces at eleven viewports; WCAG scans, pairing, command and scoped memory passed.');
} finally {await browser.close();}
