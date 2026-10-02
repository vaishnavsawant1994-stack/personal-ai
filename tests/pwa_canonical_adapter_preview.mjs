import assert from "node:assert/strict";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const axePath = process.env.PERSONAL_AI_AXE_PATH || require.resolve("axe-core/axe.min.js");
import { chromium, firefox, webkit } from "playwright";
const engine=process.env.PERSONAL_AI_BROWSER || "chromium";
assert.ok(["chromium","firefox","webkit"].includes(engine),"supported browser engine");

const executablePath=process.env.PERSONAL_AI_BROWSER_EXECUTABLE || (engine==="chromium" ? process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE : undefined);
const browser = await ({chromium,firefox,webkit})[engine].launch({headless:true,...(executablePath?{executablePath}:{})});

const auditResults=[];
async function audit(page,label){
 if(!await page.evaluate(()=>Boolean(window.axe)))await page.addScriptTag({path:axePath});
 const violations=await page.evaluate(async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa']}})).violations.map(v=>({id:v.id,targets:v.nodes.map(n=>n.target)})));
 assert.deepEqual(violations,[],label+' accessibility');
 auditResults.push({surface:label,viewport:page.viewportSize(),violations:0});
}

const conversations = [
  { id: "c1", title: "Project Planning", preview: "Continue planning the project", updated_at: "2026-09-30T12:30:00+05:30" },
  { id: "c2", title: "Mushroom Farm Plan", preview: "Shed layout and capacity", updated_at: "2026-09-30T10:15:00+05:30" },
  { id: "c3", title: "Onion Cultivation Guide", preview: "Irrigation and fertilizer plan", updated_at: "2026-09-29T09:42:00+05:30" },
];

const now = new Date();
const atToday = (hour, minute = 0) =>
  new Date(now.getFullYear(), now.getMonth(), now.getDate(), hour, minute).toISOString();
const atDayOffset = (days,hour=10) => new Date(now.getFullYear(),now.getMonth(),now.getDate()+days,hour).toISOString();
const everydayItems = [
  { id:"task-1",kind:"task",context:"personal-ai:today:task",title:"Finish daily review",due_at:atToday(9),created_at:atToday(7),updated_at:atToday(8),status:"scheduled" },
  { id:"meeting-1",kind:"commitment",context:"personal-ai:today:meeting",title:"Team planning meeting",due_at:atToday(14),created_at:atToday(8),updated_at:atToday(8),status:"scheduled" },
  { id:"work-1",kind:"task",context:"personal-ai:today:work",title:"Prepare client proposal",due_at:atDayOffset(-1,16),created_at:atDayOffset(-2,9),updated_at:atDayOffset(-1,9),status:"scheduled" },
  { id:"done-1",kind:"task",context:"personal-ai:today:task",title:"Complete weekly report",due_at:atToday(11),created_at:atToday(8),updated_at:atToday(12,20),completed_at:atToday(12,20),status:"completed" },
  { id:"reminder-1",kind:"reminder",context:"personal-ai:today:reminder",title:"Send follow-up",due_at:atDayOffset(1,10),created_at:atToday(7),updated_at:atToday(7),status:"scheduled" },
];
const auditedEvents=[{id:"audit-1",category:"workflow",kind:"workflow",label:"Workflow",action:"workflow_run_finished",status:"completed",created_at:atToday(8,15)}];
const workflowRuns=[{id:'run-1',workflow_title:'Morning operations',status:'completed',created_at:atToday(7),updated_at:atToday(9,30),current_step:3}];
let allowActivity=true;
let revokeSession=false;
const deletedConversationIds=[];
const renamedConversationIds=[];
const exportedConversationIds=[];
const turnConversationIds=[];
const logicalRequestIds=[];
let conversationCreateCount=0;
let turnClock=Date.now();

const activeConversation = {
  thread: { id: "c1", title: "Project Planning", created_at: atDayOffset(-1,23), updated_at: conversations[0].updated_at },
  events: [
    { event_id:"c1-user-1", kind: "user_message", created_at: atDayOffset(-1,23), payload: { text: "Plan mushroom farm shed layout with complete details" } },
    { event_id:"c1-assistant-1", kind: "assistant_message", created_at: atToday(0,5), payload: { text: "I can help with the shed layout, rack design, climate control, and cost planning.\n\n1. Start with rack spacing\n2. Confirm ventilation\n3. Keep `humidity` monitored" } },
  ],
};
let newConversation = {
  thread: { id:"new", title:"New conversation", created_at:new Date(turnClock).toISOString(), updated_at:new Date(turnClock).toISOString() },
  events: [],
};

try {
  const page = await browser.newPage({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 2,
    isMobile: engine!=="firefox",
    serviceWorkers: "block", // API fixtures must not be bypassed by the separately tested worker.
    hasTouch: true,
  });

  const pageErrors = [];
  const uploadedDocuments = [];
  let memoryMode="ready",releaseMemory;
  page.on("pageerror", error => pageErrors.push(error.stack || error.message));

  await page.route("**/iphone/api/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace("/iphone/api", "");
    const method = request.method();
    if(path.startsWith('/conversations/')&&method==='PATCH')renamedConversationIds.push(decodeURIComponent(path.split('/')[2]));
    if(path.startsWith('/conversations/')&&method==='DELETE')deletedConversationIds.push(decodeURIComponent(path.split('/')[2]));
    if(path==='/memory'){
      if(memoryMode==='loading')await new Promise(resolve=>{releaseMemory=resolve});
      if(memoryMode==='permission')return route.fulfill({status:403,contentType:'application/json',body:JSON.stringify({detail:'Internal trace should never be shown'})});
      if(memoryMode==='failure')return route.fulfill({status:500,contentType:'application/json',body:JSON.stringify({detail:'Internal trace should never be shown'})});
    }

    let body = {};
    if (path === "/status") {
      if(revokeSession)return route.fulfill({status:401,contentType:"application/json",body:JSON.stringify({detail:"Owner verification required"})});
      body = { model: { state: "ready" }, conversations, conversation: activeConversation, memory_count: 3, active_qualification: true };
    } else if (path === "/everyday/active" && method === "GET") {
      body = { items: everydayItems.filter(item => !['completed','cancelled','dismissed'].includes(item.status)) };
    } else if (path === "/everyday/timeline" && method === "GET") {
      body = { items: everydayItems };
    } else if (path === "/activities" && method === "GET") {
      if(!allowActivity)return route.fulfill({status:403,contentType:"application/json",body:JSON.stringify({detail:"Not authorized"})});
      body={activities:auditedEvents};
    } else if (path === "/workflows" && method === "GET") {
      body={runs:workflowRuns,workflows:[]};
    } else if (path === "/everyday/items" && method === "POST") {
      const input = JSON.parse(request.postData() || "{}");
      const item = { id: "created-" + everydayItems.length, title: input.title, kind: input.category === "meeting" ? "commitment" : input.category === "reminder" ? "reminder" : "task",
        context: "personal-ai:today:" + input.category, due_at: input.due_at, status: "scheduled" };
      everydayItems.push(item);
      return route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ item }) });
    } else if (path.startsWith("/everyday/") && path.endsWith("/complete") && method === "POST") {
      const id = decodeURIComponent(path.split("/")[2]);
      const item = everydayItems.find(item => item.id === id);
      if(item){item.status="completed";item.completed_at=new Date().toISOString();item.updated_at=item.completed_at}
      body = item || {};
    } else if (path === '/memory/graph') {
      body={nodes:[{id:'memory-qa',subject:'Project context',type:'note'}],edges:[]};
    } else if (path === '/memory/tree') {
      body={roots:[{id:'memory-qa',subject:'Project context',content:'Browser qualification fixture',children:[]}]};
    } else if (path === '/memory') {
      body={memories:[{id:'memory-qa',subject:'Project context',type:'note',content:'Browser qualification fixture with source evidence',source:'owner',confidence:1}]};
    } else if (path === '/knowledge' && method==='GET') {
      body={documents:[{id:'knowledge-qa',title:'Project notes',filename:'notes.md',source:'owner-upload',access_class:'private',size_bytes:1024}]};
    } else if (path === '/system/status') {
      body={model:{state:'available',primary_provider:'private',providers:[{id:'self_hosted',configured:true,private:true,model:'Owner model',health:{state:'available'}}]},tools:[]};
    } else if (path === '/devices') {
      body={devices:[{id:'qa-browser',name:'Qualification browser',platform:'browser',permissions:['ai:chat']}],current_device_id:'qa-browser'};
    } else if (path === '/apps-tools/tools') {
      body={tools:[{tool_id:'qa-tool',name:'Approved tool',description:'Browser qualification fixture',availability:'available',approval_policy:'owner'}]};
    } else if (path === '/apps-tools/apps') {
      body={apps:[]};
    } else if (path === '/access/security') {
      body={passkeys:[],password_configured:true,recovery_codes_remaining:1,google_configured:false};
    } else if (path === "/preferences") {
      body = { continuous_voice: true, voice_rate: 1, quiet_hours: true };
    } else if (path.startsWith("/conversations/c1/activate")) {
      body = activeConversation;
    } else if (path === "/conversations/c1" && method === "PATCH") {
      const title = JSON.parse(request.postData() || "{}").title;
      activeConversation.thread.title = title;
      conversations[0].title = title;
      body = { conversation: { ...activeConversation.thread } };
    } else if (path === "/conversations/c1/export" && method === "GET") {
      exportedConversationIds.push("c1");
      body = { version: 1, conversation: activeConversation.thread, events: activeConversation.events };
    } else if (path === "/conversations/new" && method === "DELETE") {
      if(url.searchParams.get("confirm") !== "true")return route.fulfill({ status: 422, contentType:"application/json",body:JSON.stringify({detail:"Confirmation required"})});

      body = { deleted:true, conversation_id:"new" };
    } else if (path === "/conversations/new" && method === "GET") {
      body = newConversation;
    } else if (path === "/conversations/new/activate" && method === "POST") {
      body = newConversation;
    } else if (path.startsWith("/conversations/c1")) {
      body = activeConversation;
    } else if (path.startsWith("/conversations") && method === "GET") {
      const q = (url.searchParams.get("q") || "").toLowerCase();
      body = { conversations: conversations.filter(item => item.title.toLowerCase().includes(q)) };
    } else if (path === "/conversations" && method === "POST") {
      conversationCreateCount++;
      const createdAt=new Date(++turnClock).toISOString();
      newConversation={thread:{id:"new",title:"New conversation",created_at:createdAt,updated_at:createdAt},events:[]};
      body = { conversation: { ...newConversation.thread }, events: [] };
    } else if (path === "/voice/turn" && method === "POST") {
      const input = JSON.parse(request.postData() || "{}");
      logicalRequestIds.push(input.request_id);
      assert.equal(request.headers()["content-type"],"application/json");
      const text = input.transcript;
      turnConversationIds.push(input.conversation_id);
      const userAt=new Date(turnClock+=60000).toISOString(),assistantAt=new Date(turnClock+=60000).toISOString();
      const reply="Received: "+text;
      newConversation.events.push(
        {event_id:"new-"+newConversation.events.length+"-u",kind:"user_message",created_at:userAt,payload:{text}},
        {event_id:"new-"+newConversation.events.length+"-a",kind:"assistant_message",created_at:assistantAt,payload:{text:reply}}
      );
      newConversation.thread.title=newConversation.events.length===2?text.slice(0,72):newConversation.thread.title;
      newConversation.thread.updated_at=assistantAt;
      body = { status: "ok", conversation_id: "new", conversation_title: newConversation.thread.title, reply };
    } else if (path === "/knowledge" && method === "POST") {
      uploadedDocuments.push(JSON.parse(request.postData() || "{}"));
      body = { id: "browser-test-document", filename: uploadedDocuments.at(-1).filename };
    } else if (path === "/logout") {
      body = { ok: true };
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });

  await page.route("https://accounts.google.com/**", route => route.abort());
  await page.goto('http://127.0.0.1:4173/iphone/',{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.body.classList.contains('home-landing'));
  await page.addScriptTag({path:'pwa/v1-runtime.js'});
  for(const [index,text] of ['Preview canonical first turn','Preview canonical second turn'].entries()){
    await page.fill('#message',text);await page.click('#sendButton');
    await page.waitForFunction(count=>document.querySelectorAll('.message-time:not(.pending)').length===count,2*(index+1));
  }
  assert.equal(await page.evaluate(()=>currentConversationId),'new');
  assert.deepEqual(turnConversationIds,[null,'new'],'canonical adapter starts fresh then retains returned conversation');
  assert.equal(new Set(logicalRequestIds).size,2,'each turn keeps its unique logical request');
  assert.ok(logicalRequestIds.every(id=>/^[0-9a-f-]{36}$/i.test(id)),'secure logical request UUIDs');
  assert.equal(await page.locator('#chatMenuButton').isVisible(),true,'menu appears for returned canonical conversation');
  assert.equal(await page.locator('.message-time.pending').count(),0,'persisted canonical timestamps replace pending metadata');
  assert.deepEqual(await page.locator('.message-time').evaluateAll(nodes=>nodes.map(node=>node.dateTime)),newConversation.events.map(event=>event.created_at));
  assert.deepEqual(pageErrors,[]);
  await page.screenshot({path:'artifacts/personal-ai-canonical-adapter-chat-390x844.png'});
  console.log('Live canonical adapter: fresh conversation, turn IDs, JSON transport, timestamps and actions passed');
}finally{await browser.close()}
