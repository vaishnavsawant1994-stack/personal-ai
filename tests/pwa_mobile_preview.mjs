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
const auditedEvents=[{id:"audit-1",category:"workflow",kind:"workflow",label:"Workflow",action:"workflow_run_completed",status:"completed",created_at:atToday(8,15),details:{workflow_title:"Morning operations"}}];
const workflowRuns=[{id:'run-1',workflow_title:'Morning operations',status:'completed',created_at:atToday(7),updated_at:atToday(9,30),current_step:3}];
let allowActivity=true;
let revokeSession=false;
const deletedConversationIds=[];
const renamedConversationIds=[];
const exportedConversationIds=[];
const turnConversationIds=[];
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
      body={documents:[{id:'knowledge-qa',title:'Project notes',filename:'notes.md',media_type:'text/markdown',source:'owner-upload:iphone',access_class:'private',size_bytes:1024,indexed_chunk_count:2,updated_at:atToday(8)}]};
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
  await page.goto("http://127.0.0.1:4173/iphone/", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => !document.querySelector("#voicePanel").classList.contains("hidden"));
  await page.waitForFunction(() => document.body.classList.contains("home-landing"));
  await page.waitForFunction(() => {
    const canvas = document.querySelector("#neuralCanvas");
    return canvas.width > 0 && canvas.height > 0;
  });
  await page.waitForFunction(() => document.querySelectorAll("#todayTimeline .today-item").length === 2);
  await page.waitForTimeout(500);

  const canvasInk = await page.evaluate(() => {
    const canvas = document.querySelector("#neuralCanvas");
    const pixels = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data;
    let ink = 0;
    for (let i = 0; i < pixels.length; i += 4) {
      if (pixels[i + 3] > 12 && (pixels[i] > 80 || pixels[i + 1] > 100 || pixels[i + 2] > 150)) ink++;
    }
    return ink;
  });
  assert.ok(canvasInk > 90, "original mini neural sphere renderer did not paint");

  const homeState = await page.evaluate(() => ({
    bottomNavPresent: Boolean(document.querySelector(".nav")),
    quickActions: [...document.querySelectorAll(".quick-action")].map(node => node.textContent.replace(/\s+/g, " ").trim()),
    menuButton: document.querySelector("#historyButton").getBoundingClientRect(),
    composer: document.querySelector("#composer").getBoundingClientRect(),
    core: document.querySelector(".core-stage").getBoundingClientRect(),
    timeline: [...document.querySelectorAll("#todayTimeline .today-item strong")].map(node => node.textContent),
    timelineTimes: [...document.querySelectorAll("#todayTimeline .today-time")].map(node => node.textContent),
    todayTitle: document.querySelector("#todayHeading").textContent,
    headerSphere: Boolean(document.querySelector(".topbar #neuralCanvas")),
    headerGreenDot: Boolean(document.querySelector(".topbar .status-dot")),
    actionTitles: [...document.querySelectorAll(".quick-action strong")].map(node => node.textContent),
    cardRects: [...document.querySelectorAll(".quick-action")].map(node => { const r=node.getBoundingClientRect(); return {width:r.width,height:r.height} }),
    homeWidth: document.querySelector(".home-intro").getBoundingClientRect().width,
    recent: document.querySelector(".recent-feed").getBoundingClientRect().toJSON(),
    today: document.querySelector(".today-panel").getBoundingClientRect().toJSON(),
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth,
    innerHeight,
  }));
  assert.equal(await page.locator("#chatMenuButton").isVisible(), false, "three-dot conversation menu must be absent on Home");
  assert.equal(await page.evaluate(() => currentConversationId), null, "Home must not remain bound to the previously active conversation");
  assert.equal(await page.locator("#messageStream .message").count(), 0, "Home must clear the resumed chat from the new-chat draft surface");
  assert.equal(homeState.bottomNavPresent, false, "persistent bottom navigation must be removed");
  assert.equal(homeState.quickActions.length, 4, "home must expose four real quick actions");
  assert.deepEqual(homeState.actionTitles, ["Chat", "Create", "Imagine", "Tools"]);
  assert.ok(homeState.cardRects.every(card => Math.abs(card.height-homeState.cardRects[0].height)<1 && Math.abs(card.width-homeState.cardRects[0].width)<1), "four Home cards must be exactly equal sized");
  assert.ok(homeState.composer.width <= homeState.homeWidth-10, "Home composer must be narrower than the cards");
  assert.ok(homeState.cardRects.every(card => card.height <= 90), "Home tiles must remain the SMALL original card size");
  assert.ok(homeState.composer.height >= 47 && homeState.composer.height <= 50, "Home composer must be compact, close to an SMS field");
  assert.equal(await page.locator("#sendButton").isVisible(), false, "idle composer must show microphone, not inactive send");
  assert.equal(await page.locator("#micButton").isVisible(), true, "idle composer microphone must remain available");
  assert.equal(await page.locator("#attachmentButton svg path").getAttribute("d"), "M12 5v14M5 12h14", "attachment icon must be a compact plus");
  assert.equal(await page.locator("#attachmentButton").getAttribute("aria-label"), "Add a document", "compact plus must retain the accessible attachment label");
  assert.equal(homeState.headerSphere, true, "original sphere must occupy compact top header");
  assert.equal(homeState.headerGreenDot, false, "top status dot must be removed");
  assert.equal(homeState.todayTitle, "Today");
  assert.ok(homeState.recent.bottom <= homeState.today.top + 1, "Recent feed must not overlap the Today panel on mobile");
  assert.deepEqual(homeState.timeline, ["Finish daily review","Team planning meeting"], "Today timeline must show REAL canonical items, not conversations or fake meetings");
  assert.ok(homeState.cardRects.every(card => card.height <= 70), "four Home cards must be genuinely slim");
  assert.equal(await page.locator("#recentList .recent-feed-row").count(), 3, "Recent must show canonical saved conversations alongside Today tasks");
  assert.equal(await page.locator(".prompt-chips, [data-prompt]").count(), 0, "bottom suggestion strip must be fully removed");
  assert.ok(homeState.menuButton.width >= 44 && homeState.menuButton.height >= 44, "hamburger target must be at least 44px");
  assert.ok(homeState.core.width > 0 && homeState.core.height > 0, "sphere must remain visible on Home");
  assert.ok(homeState.composer.bottom <= homeState.innerHeight + 1, "composer must remain inside the viewport");
  assert.ok(homeState.scrollWidth <= homeState.innerWidth, "home must not scroll horizontally");
  await audit(page,"home-390x844");
  await page.screenshot({ path: "artifacts/personal-ai-home-390x844.png", fullPage: true });
  // Today timeline is real: add a meeting, mark a task complete, verify empty-state.
  await page.click("#todayAdd");
  assert.ok(await page.locator("#todayForm").isVisible(), "Add control must reveal accessible item form");
  await page.selectOption("#todayCategory", "meeting");
  await page.fill("#todayTitle", "Afternoon planning review");
  await page.fill("#todayTime", "15:30");
  await page.click("#todaySave");
  await page.waitForFunction(() => document.querySelectorAll("#todayTimeline .today-item").length === 3);
  assert.deepEqual(await page.locator("#todayTimeline .today-item strong").allTextContents(),
    ["Finish daily review","Team planning meeting","Afternoon planning review"], "Today items must be sorted chronologically");
  await page.locator("#todayTimeline .today-check").first().click();
  await page.waitForFunction(() => document.querySelectorAll("#todayTimeline .today-item").length === 2);
  assert.ok(!((await page.locator("#todayTimeline").innerText()).includes("Finish daily review")), "completing a task must remove it from today's pending list");
  await page.evaluate(() => renderToday([]));
  assert.ok((await page.locator("#todayTimeline").innerText()).includes("Nothing planned yet"), "empty Today panel must not invent calendar meetings");
  await audit(page,"Today empty");
  await page.evaluate(()=>todayLoadError(new Error("Fixture failure")));
  await audit(page,"Today unavailable");
  await page.locator("#todayTimeline button").click();
  await page.waitForFunction(()=>document.querySelectorAll("#todayTimeline .today-item").length===2);

  // The conversation-first sidebar keeps owner security behind its anchored account footer.
  await page.click("#historyButton");
  await page.waitForFunction(() => document.querySelectorAll("#sidebarChatList .sidebar-chat-row").length === 3);
  assert.ok(await page.locator("#sidebarAccountButton").isVisible(), "account controls must be anchored to bottom");
  await page.click("#sidebarAccountButton");
  assert.equal(await page.locator("#sidebarAccountButton").getAttribute("aria-expanded"), "true", "account popover must advertise expanded state");
  for (const label of ["Owner controls","Settings","Trusted devices","System status","Sign out"]) {
    assert.ok((await page.locator("#sidebarAccountMenu").innerText()).includes(label), "account controls missing " + label);
  }
  await page.screenshot({ path: "artifacts/personal-ai-sidebar-account-390x844.png", fullPage: true });
  await page.click("#appOwnerControls");
  await page.waitForFunction(() => !document.querySelector("#ownerMenu").classList.contains("hidden"));
  for (const item of ["Settings", "Trusted devices", "System status", "Sign out this browser"]) {
    assert.ok((await page.locator("#ownerMenu").innerText()).includes(item), "Owner Controls missing " + item);
  }
  await page.screenshot({ path: "artifacts/personal-ai-owner-controls-390x844.png", fullPage: true });
  await page.keyboard.press("Escape");
  await page.waitForFunction(() => document.querySelector("#ownerMenu").classList.contains("hidden"));

  // Direct header history opens the secondary panel from the right, without the main sidebar.
  await page.click("#ownerButton");
  await page.waitForFunction(() => {
    const drawer = document.querySelector("#conversationDrawer");
    const rect=drawer.getBoundingClientRect();
    return !drawer.classList.contains("hidden") && rect.left>=-1 && Math.abs(rect.right-innerWidth)<=1;
  });
  assert.equal(await page.locator("#appDrawer").isVisible(),false,"direct history must not open the main hamburger sidebar");
  assert.equal(await page.locator("#closeDrawer").getAttribute("aria-label"),"Close timeline");
  await page.screenshot({ path: "artifacts/personal-ai-right-conversations-direct-390x844.png", fullPage: true });
  await page.click("#closeDrawer");
  await page.waitForFunction(() => document.querySelector("#conversationDrawer").classList.contains("hidden"));
  assert.equal(await page.locator("#appDrawer").isVisible(),false,"closing directly-opened conversations must not show the main sidebar");

  await page.click("#historyButton");
  await page.waitForFunction(() => !document.querySelector("#appDrawer").classList.contains("hidden"));
  await page.waitForFunction(() => document.querySelectorAll("#sidebarChatList .sidebar-chat-row").length === 3);
  await page.waitForFunction(() => document.querySelector("#appDrawer").getBoundingClientRect().left >= -1);
  const drawerState = await page.evaluate(() => ({
    labels: [...document.querySelectorAll("#appDrawer .sidebar-nav-row span")].map(node => node.textContent.trim()),
    chatTitles: [...document.querySelectorAll("#sidebarChatList .sidebar-chat-row span")].map(node => node.textContent.trim()),
    rect: (() => { const r=document.querySelector("#appDrawer").getBoundingClientRect(); return {left:r.left,width:r.width}; })(),
    footer: (() => { const r=document.querySelector("#sidebarAccountButton").getBoundingClientRect(); return {bottom:r.bottom,height:r.height}; })(),
    expanded: document.querySelector("#historyButton").getAttribute("aria-expanded"),
  }));
  for (const expected of ["Home","Today","Conversations","Memory","Knowledge","Activities","Tools","Workflows"]) {
    assert.ok(drawerState.labels.includes(expected), "missing functional sidebar section: " + expected);
  }
  assert.deepEqual(drawerState.chatTitles, conversations.map(item=>item.title), "main sidebar must display real canonical conversation history");
  assert.equal(drawerState.expanded, "true", "hamburger aria-expanded must track the sidebar");
  assert.ok(drawerState.rect.width <= 390 && drawerState.rect.left >= -1, "sidebar must fit mobile viewport");
  assert.ok(drawerState.footer.bottom <= 845 && drawerState.footer.height >= 44, "account actions must remain visible and touchable");
  assert.ok(await page.locator("#sidebarNewChat").isVisible(), "new chat must be a primary action");
  assert.ok(await page.locator("#sidebarSearchToggle").isVisible(), "chat search must be a primary action");
  await audit(page,"menu-390x844");
  await page.screenshot({ path: "artifacts/personal-ai-menu-390x844.png", fullPage: true });
  await page.click("#sidebarSearchToggle");
  assert.equal(await page.locator("#sidebarSearchToggle").getAttribute("aria-expanded"), "true");
  await page.evaluate(() => document.documentElement.style.setProperty("--sidebar-visible-height","540px"));
  const keyboardSidebar = await page.evaluate(() => ({
    pane: document.querySelector("#appDrawer").getBoundingClientRect(),
    account: document.querySelector("#sidebarAccountButton").getBoundingClientRect(),
  }));
  assert.ok(keyboardSidebar.pane.height <= 541 && keyboardSidebar.account.bottom <= 541,
    "sidebar footer must remain within reduced keyboard-height viewport");
  await page.evaluate(() => syncSidebarViewport());
  await page.fill("#sidebarSearch", "Onion");
  await page.waitForFunction(() => document.querySelectorAll("#sidebarChatList .sidebar-chat-row").length === 1 && document.querySelector("#sidebarChatList").textContent.includes("Onion"));
  await page.fill("#sidebarSearch", "not-a-real-chat");
  await page.waitForFunction(() => document.querySelector("#sidebarChatList")?.textContent.includes("No matching conversations"));
  await page.click("#sidebarSearchClear");
  await page.waitForFunction(() => document.querySelectorAll("#sidebarChatList .sidebar-chat-row").length === 3);
  await page.click("#sidebarSearchToggle");
  assert.equal(await page.locator("#sidebarSearchPanel").isVisible(), false, "search must collapse cleanly");

  await page.click('#appConversations');
  await page.waitForFunction(()=>document.querySelectorAll('#historyList .history-row').length===3);
  assert.equal(await page.locator('#conversationDrawer').isVisible(),false,'History must be independent from Timeline');
  await page.fill('#historySearch','Onion');
  await page.waitForFunction(()=>document.querySelectorAll('#historyList .history-row').length===1);
  assert.match(await page.locator('#historyList').innerText(),/Onion/);
  await page.click('#historyList summary');
  await audit(page,'History context actions');
  await page.screenshot({path:'artifacts/personal-ai-history-context-menu-390x844.png',fullPage:true});
  await page.keyboard.press('Escape');
  assert.ok(await page.locator('#historyDrawer').isVisible(),'Escape closes history actions before closing the panel');
  await page.click('#historyList summary');await page.click('#historyList .history-action-list button:not(.danger)');
  await page.click('#uiDialogCancel');
  assert.deepEqual(renamedConversationIds,[],'cancelled history rename must not change canonical data');
  await page.click('#historyList summary');await page.click('#historyList .history-action-list button.danger');
  await page.click('#uiDialogCancel');
  assert.deepEqual(deletedConversationIds,[],'cancelled history delete must leave the conversation intact');
  await audit(page,"history-390x844");
  await page.screenshot({path:'artifacts/personal-ai-history-390x844.png',fullPage:true});
  await page.click('#historyClose');
  assert.equal(await page.locator('#appDrawer').isVisible(),true,'History close returns to its originating menu');
  await page.evaluate(()=>openDrawer());
  await page.waitForFunction(() => {
    const panel=document.querySelector("#conversationDrawer");
    return !panel.classList.contains("hidden") && panel.getBoundingClientRect().left>=-1 &&
      Math.abs(panel.getBoundingClientRect().right-innerWidth)<=1;
  });
  await page.waitForFunction(() => document.querySelectorAll(".timeline-entry").length >= 10);
  assert.equal(await page.locator("#appDrawer").isVisible(),false,"right Timeline must replace open left drawer");
  assert.equal(await page.locator("#closeDrawer").getAttribute("aria-label"),"Back to main menu");
  const timelineState=await page.evaluate(()=>({
    filters:[...document.querySelectorAll(".conversation-filter")].map(n=>n.textContent.trim()),
    titles:[...document.querySelectorAll(".timeline-title")].map(n=>n.textContent.trim()),
    categories:[...document.querySelectorAll(".timeline-entry")].map(n=>n.dataset.category),
    clocks:[...document.querySelectorAll(".timeline-clock")].map(n=>new Date(n.dateTime).getTime()),
    rect:document.querySelector("#conversationDrawer").getBoundingClientRect(),
    width:innerWidth,cssRight:getComputedStyle(document.querySelector("#conversationDrawer")).right,
  }));
  assert.deepEqual(timelineState.filters,["All","Recent","Chats","Meetings","Tasks","Work","Reminders","Workflows","Done","Activity"]);
  assert.ok(timelineState.titles.includes("Complete weekly report"),"completed work must show recorded completion time");
  assert.ok(timelineState.titles.includes("Team planning meeting"),"real saved meetings must appear");
  assert.ok(timelineState.categories.includes("activity"),"authorized audit events must appear without fabrication");
  assert.ok(timelineState.clocks.every((stamp,i,a)=>i===0||a[i-1]>=stamp),"mixed records must sort chronologically");
  assert.ok(Math.abs(timelineState.rect.right-timelineState.width)<=1&&timelineState.rect.left>0,"Timeline must stay right-aligned");
  assert.equal(timelineState.cssRight,"0px");
  assert.ok((await page.locator("#conversationCount").innerText()).includes("pending"));
  assert.ok((await page.locator('.timeline-entry[data-status="done"]').count())>=2);
  assert.ok(await page.locator("#timelineAddPlan").isVisible(),"right timeline must let owner plan work");
  assert.ok((await page.locator("#timelineAddPlan").boundingBox()).width<180,"timeline planning action stays compact in the sidebar");
  assert.equal(await page.locator("#conversationDrawer").getAttribute("aria-label"),"Timeline");
  assert.equal(await page.locator("#newConversation").count(),0,"Timeline controls stay focused on chronology and planning");
  await audit(page,"unified-timeline-all-390x844");
  await page.screenshot({path:"artifacts/personal-ai-unified-timeline-all-390x844.png",fullPage:true});
  await page.locator('[data-conversation-filter="meeting"]').click();
  assert.deepEqual(await page.locator(".timeline-title").allTextContents(),["Afternoon planning review","Team planning meeting"]);
  await page.locator('[data-conversation-filter="work"]').click();
  assert.deepEqual(await page.locator(".timeline-title").allTextContents(),["Prepare client proposal"]);
  await page.locator('[data-conversation-filter="done"]').click();
  assert.ok((await page.locator(".timeline-title").allTextContents()).includes("Complete weekly report"));
  await page.locator('[data-conversation-filter="workflow"]').click();
  assert.deepEqual(await page.locator(".timeline-title").allTextContents(),["Morning operations"]);
  await page.locator('[data-conversation-filter="activity"]').click();
  assert.deepEqual(await page.locator(".timeline-title").allTextContents(),["Workflow"]);
  await page.locator('[data-conversation-filter="reminder"]').click();
  assert.deepEqual(await page.locator(".timeline-title").allTextContents(),["Send follow-up"]);
  await page.locator('[data-conversation-filter="conversation"]').click();
  assert.deepEqual(await page.locator(".timeline-title").allTextContents(),conversations.map(x=>x.title));
  await page.locator('[data-conversation-filter="all"]').click();
  await page.fill("#conversationSearch","Onion");
  await page.waitForFunction(()=>document.querySelectorAll(".timeline-entry").length===1&&document.querySelector(".timeline-title").textContent.includes("Onion"));
  assert.ok((await page.locator("#conversationCount").innerText()).startsWith("1 entry"));
  await page.locator('[data-conversation-filter="recent"]').click();
  assert.equal(await page.locator('[data-conversation-filter="recent"]').getAttribute("aria-pressed"),"true");
  assert.ok((await page.locator(".timeline-title").allTextContents()).includes("Onion Cultivation Guide"),"Recent must preserve cross-category search results");
  await page.locator('[data-conversation-filter="all"]').click();
  await page.fill("#conversationSearch","weekly report");
  await page.waitForFunction(()=>document.querySelectorAll(".timeline-entry").length===1&&document.querySelector(".timeline-title").textContent.includes("Complete weekly report"));
  await page.fill("#conversationSearch","nonexistent title");
  await page.waitForFunction(()=>document.querySelectorAll(".timeline-entry").length===0&&document.querySelector(".timeline-empty")?.textContent.includes("No matching"));
  await page.fill("#conversationSearch","");
  await page.waitForFunction(()=>document.querySelectorAll(".timeline-entry").length>=10);
  await page.locator('[data-conversation-filter="work"]').click();
  await page.locator('.timeline-entry[data-category="work"] .timeline-complete').click();
  await page.waitForFunction(()=>document.querySelector('.timeline-entry[data-category="work"]')?.dataset.status==="done");
  await page.locator('[data-conversation-filter="done"]').click();
  assert.ok((await page.locator(".timeline-title").allTextContents()).includes("Prepare client proposal"),"Mark done must persist and update the timeline");
  await page.locator('[data-conversation-filter="activity"]').click();
  allowActivity=false;
  await page.evaluate(()=>refreshUnifiedTimeline(''));
  await page.waitForFunction(()=>document.querySelector(".timeline-notice")?.textContent.includes("not permitted"));
  assert.equal(await page.locator('.timeline-entry[data-category="activity"]').count(),0,"restricted audited activity must not leak");
  allowActivity=true;
  await page.locator('[data-conversation-filter="all"]').click();
  await page.evaluate(()=>refreshUnifiedTimeline(''));
  await page.waitForFunction(()=>document.querySelector('.timeline-entry[data-category="activity"]'));
  await page.screenshot({path:"artifacts/personal-ai-unified-timeline-filtered-390x844.png",fullPage:true});
  await page.click("#closeDrawer");
  await page.waitForFunction(() => document.querySelector("#conversationDrawer").classList.contains("hidden") &&
    !document.querySelector("#appDrawer").classList.contains("hidden"));
  assert.equal(await page.locator("#historyButton").getAttribute("aria-expanded"),"true","Back must restore left main sidebar");
  assert.equal(await page.locator("#appConversations").isVisible(),true,"returned left menu must remain functional");
  assert.deepEqual(await page.locator("#sidebarChatList .sidebar-chat-row span").allTextContents(),
    conversations.map(item=>item.title),"search in right drawer must not destroy main sidebar chat history");
  await page.waitForFunction(() => document.querySelectorAll("#sidebarChatList .sidebar-chat-row").length === 3);
  await page.locator("#sidebarChatList .sidebar-chat-row").first().click();
  await page.waitForFunction(() => document.querySelector("#appDrawer").classList.contains("hidden") && !document.body.classList.contains("home-landing"));
  assert.ok((await page.locator("#messageStream").innerText()).includes("Plan mushroom farm"), "sidebar chat selection must open the actual persisted conversation");
  await page.click("#historyButton");
  await page.evaluate(()=>openDrawer());

  await page.locator(".timeline-entry[data-category=conversation] .timeline-title").first().click();
  await page.waitForFunction(() => !document.body.classList.contains("home-landing"));
  await page.waitForFunction(() => document.querySelectorAll("#messageStream .message").length === 2);
  const chatState = await page.evaluate(() => ({
    coreVisibility: getComputedStyle(document.querySelector(".core-stage")).visibility,
    messageCount: document.querySelectorAll("#messageStream .message").length,
    messages: document.querySelector("#messageStream").getBoundingClientRect(),
    composer: document.querySelector("#composer").getBoundingClientRect(),
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth,
    innerHeight,
  }));
  assert.equal(chatState.coreVisibility, "visible", "compact original sphere remains visible in the header while chatting");
  assert.ok(await page.evaluate(()=>Array.from({length:360},(_,frame)=>colorShiftPalette(frame)).every(([r,g,b])=>b>g&&g>r)),"idle sphere palette stays in Personal AI blue and cyan hues");
  const statusVisual = await page.locator(".state").evaluate(node => {
    const style = getComputedStyle(node);
    const rect = node.getBoundingClientRect();
    return { position: style.position, overflow: style.overflow, width: rect.width, height: rect.height };
  });
  assert.ok(statusVisual.position === "absolute" && statusVisual.overflow === "hidden" && statusVisual.width <= 1 && statusVisual.height <= 1,
    "voice status remains announced to assistive technology without adding visible thinking labels");
  assert.equal((await page.locator("#stateLabel").innerText()).trim().toUpperCase(),"ACTIVE","idle conversation status must match the approved reference");
  assert.equal(await page.locator("#status").isVisible(),false,"idle ACTIVE status must stay visually minimal without redundant helper copy");
  assert.equal(chatState.messageCount, 2);
  assert.equal(await page.locator(".message-time").count(),2,"every persisted message must render its canonical timestamp");
  assert.deepEqual(await page.locator(".message-time").evaluateAll(nodes=>nodes.map(node=>node.dateTime)),activeConversation.events.map(event=>event.created_at),"DOM timestamps must come from persisted event creation time");
  assert.equal(await page.locator(".date-separator").count(),2,"calendar-date changes must create one subtle separator per day");
  assert.equal(await page.locator(".message-entry.assistant .message-avatar").count(),0,"assistant responses must not repeat an orb avatar; the original header sphere carries Personal AI identity");
  assert.equal(await page.locator(".message-entry.assistant ol li").count(),3,"numbered Markdown must render structurally");
  assert.equal(await page.locator(".message-entry.assistant code").count(),1,"inline code must render structurally");
  const messageVisual=await page.evaluate(()=>({
    assistantBackground:getComputedStyle(document.querySelector(".message.assistant")).backgroundColor,
    assistantBorder:getComputedStyle(document.querySelector(".message.assistant")).borderTopWidth,
    user:document.querySelector(".message.user").getBoundingClientRect(),
    stream:document.querySelector("#messageStream").getBoundingClientRect(),
    footer:document.querySelector(".message-entry.assistant .message-footer").getBoundingClientRect(),
  }));
  assert.equal(messageVisual.assistantBackground,"rgba(0, 0, 0, 0)","AI responses must use an open transparent surface instead of a boxed card");
  assert.equal(messageVisual.assistantBorder,"0px","AI responses must not retain the old card border");
  assert.ok(messageVisual.user.right>=messageVisual.stream.right-8,"owner bubble must align to the right edge");
  assert.ok(messageVisual.user.width<=messageVisual.stream.width*.83,"owner bubble must remain compact rather than becoming a full-width card");
  assert.ok(messageVisual.footer.width>0,"message metadata and actions must share one aligned footer row");
  assert.equal(await page.locator(".message-entry.assistant .message-footer .message-time").count(),1);
  assert.equal(await page.locator(".message-entry.assistant .message-footer .message-actions").count(),1);
  assert.equal(await page.locator(".message-entry.user .message-actions button").count(),2,"user messages expose copy and edit");
  assert.equal(await page.locator(".message-entry.assistant .message-actions button").count(),5,"assistant messages expose copy, feedback, speech and share");
  assert.equal(await page.locator('.message-entry.assistant [aria-label="Good response"]').getAttribute("aria-pressed"),"false");
  await page.locator('.message-entry.assistant [aria-label="Good response"]').click();
  assert.equal(await page.locator('.message-entry.assistant [aria-label="Good response"]').getAttribute("aria-pressed"),"true","positive feedback has selected visual state");
  await page.locator('.message-entry.assistant [aria-label="Bad response"]').click();
  assert.equal(await page.locator('.message-entry.assistant [aria-label="Good response"]').getAttribute("aria-pressed"),"false","negative feedback deselects positive feedback");
  assert.equal(await page.locator('.message-entry.assistant [aria-label="Bad response"]').getAttribute("aria-pressed"),"true");

  assert.ok(chatState.messages.height > 0, "active conversation needs a real scroll viewport");
  assert.ok(chatState.composer.bottom <= chatState.innerHeight + 1, "chat composer must remain visible");
  assert.ok(chatState.scrollWidth <= chatState.innerWidth, "active conversation must not overflow horizontally");
  assert.equal(await page.locator("#chatMenuButton").isVisible(), true, "three-dot menu must appear after loading a real conversation");
  const headerButtons=await page.evaluate(()=>({
    more:document.querySelector("#chatMenuButton").getBoundingClientRect(),
    timeline:document.querySelector("#ownerButton").getBoundingClientRect(),
  }));
  assert.ok(headerButtons.more.right <= headerButtons.timeline.left+1, "conversation menu must sit LEFT of the right-side timeline button");
  assert.ok(headerButtons.more.width>=44&&headerButtons.more.height>=44, "conversation menu must retain accessible touch target");
  await page.click("#chatMenuButton");
  assert.equal(await page.locator("#chatActionMenu").isVisible(),true,"three-dot menu must open");
  assert.deepEqual(await page.locator("#chatActionMenu [role=menuitem]").allTextContents(),
    ["Rename","Share transcript","Copy transcript","Download JSON","Delete conversation"],"conversation menu must expose only connected actions");
  await page.keyboard.press("Escape");
  assert.equal(await page.locator("#chatActionMenu").isVisible(),false,"Escape must close the conversation menu");
  await page.click("#chatMenuButton");
  await page.click("#chatRename");
  await page.fill("#uiDialogInput","Mushroom Session Notes");
  await page.click("#uiDialogAccept");
  await page.waitForFunction(()=>document.querySelector("#conversationTitle").textContent==="Mushroom Session Notes");
  assert.equal(conversations[0].title,"Mushroom Session Notes","rename must call the real conversation API");
  await page.evaluate(()=>{
    Object.defineProperty(navigator,"clipboard",{configurable:true,value:{writeText:async text=>{window.__copiedTranscript=text}}});
    Object.defineProperty(navigator,"share",{configurable:true,value:async data=>{window.__sharedTranscript=data}});
  });
  await page.click("#chatMenuButton");
  await page.click("#chatCopy");
  await page.waitForFunction(()=>Boolean(window.__copiedTranscript));
  assert.ok((await page.evaluate(()=>window.__copiedTranscript)).includes("Plan mushroom farm shed"),"copy must use the real transcript");
  await page.click("#chatMenuButton");
  await page.click("#chatShare");
  await page.waitForFunction(()=>Boolean(window.__sharedTranscript));
  assert.ok((await page.evaluate(()=>window.__sharedTranscript.text)).includes("Plan mushroom farm shed"),"share must send transcript text, not manufacture a public link");
  await page.click("#chatMenuButton");
  const exportDownload=page.waitForEvent("download");
  await page.click("#chatExport");
  await exportDownload;
  assert.deepEqual(exportedConversationIds,["c1"],"download must request the authenticated canonical export");
  await page.evaluate(()=>{messageReactions.clear();renderMessages();setState('idle');document.querySelector('#toast')?.classList.add('hidden')});
  await audit(page,"chat-390x844");
  await page.screenshot({ path: "artifacts/personal-ai-chat-390x844.png", fullPage: true });
  await page.screenshot({ path: "artifacts/personal-ai-chat-date-separated-390x844.png", fullPage: true });

  const longResponseFixture=await page.evaluate(()=>{
    const event={
      event_id:"visual-long-response",kind:"assistant_message",created_at:new Date().toISOString(),
      payload:{text:"## Detailed plan\n\nThis is a deliberately long Personal AI response used to verify that open assistant content stays readable and wide without being forced into a phone-chat bubble.\n\n- Preserve the original neural sphere\n- Keep the composer visible above the safe area\n- Keep actions close to the response\n\n```text\nLong content remains inside the same response block.\nNo token-sized bubbles are created.\n```\n\n| Check | Result |\n| --- | --- |\n| Wrapping | Correct |\n| Overflow | None |"}
    };conversationEvents.push(event);renderMessages();return event;
  });
  activeConversation.events.push(longResponseFixture);
  await page.waitForFunction(()=>document.querySelectorAll(".message-entry.assistant").length===2);
  assert.ok(await page.locator(".message-entry.assistant").last().locator("pre code").isVisible(),"long response code block must remain readable");
  assert.ok(await page.locator(".message-entry.assistant").last().locator("table").isVisible(),"long response Markdown table must render");
  await page.locator('.code-copy').last().click();
  assert.match(await page.evaluate(()=>window.__copiedTranscript),/Long content remains/,'code copy uses only the canonical block text');
  await page.evaluate(()=>{const stream=$('messageStream');stream.scrollTop=80;stream.dispatchEvent(new Event('scroll'));const before=stream.scrollTop;renderMessages();window.__preservedOffset={before,after:stream.scrollTop}});
  const preservedOffset=await page.evaluate(()=>window.__preservedOffset);
  assert.ok(preservedOffset.before>0&&Math.abs(preservedOffset.before-preservedOffset.after)<1,'updating messages must preserve the reader’s scroll position');
  assert.ok(await page.locator('#scrollLatest').isVisible(),'show latest control when reading older messages');
  await page.click('#scrollLatest');
  await page.waitForFunction(()=>{const stream=$('messageStream');return stream.scrollHeight-stream.clientHeight-stream.scrollTop<48});
  assert.ok(await page.locator('#scrollLatest').isHidden(),'latest control disappears near the bottom');
  await page.evaluate(()=>{setState('idle');document.querySelector('#toast')?.classList.add('hidden')});
  await page.screenshot({ path: "artifacts/personal-ai-chat-long-response-390x844.png", fullPage: true });

  const longThreadPerformance=await page.evaluate(()=>{
    const original=conversationEvents;let result;
    try{
      const canonicalTime=original.find(event=>event.created_at)?.created_at;
      conversationEvents=Array.from({length:300},(_,index)=>({kind:index%2?'assistant_message':'user_message',created_at:canonicalTime,payload:{text:'Performance fixture message '+index}}));
      const start=performance.now();renderMessages();result={messages:document.querySelectorAll('.message-entry').length,renderMs:performance.now()-start};
    }finally{conversationEvents=original;conversationPinnedToBottom=true;renderMessages()}
    return result;
  });
  assert.equal(longThreadPerformance.messages,300,'large histories remain one message per canonical event');
  assert.ok(longThreadPerformance.renderMs<3000,'large conversation must render within a bounded interval');
  activeConversation.events=activeConversation.events.filter(event=>event.event_id!=="visual-long-response");
  await page.evaluate(()=>openConversation("c1"));
  await page.waitForFunction(()=>document.querySelectorAll("#messageStream .message").length===2);
  const persistedTimesBeforeRefresh=await page.locator(".message-time").evaluateAll(nodes=>nodes.map(node=>({dateTime:node.dateTime,text:node.textContent})));
  await page.reload({waitUntil:"domcontentloaded"});
  await page.waitForFunction(()=>document.body.classList.contains("home-landing"));
  assert.equal(await page.evaluate(()=>currentConversationId),null,"refresh must still land on a fresh Home draft instead of silently reopening an old chat");
  await page.evaluate(()=>openConversation("c1"));
  await page.waitForFunction(()=>document.querySelectorAll("#messageStream .message").length===2);
  const persistedTimesAfterRefresh=await page.locator(".message-time").evaluateAll(nodes=>nodes.map(node=>({dateTime:node.dateTime,text:node.textContent})));
  assert.deepEqual(persistedTimesAfterRefresh,persistedTimesBeforeRefresh,"refresh must preserve original canonical message timestamps");
  await page.screenshot({ path: "artifacts/personal-ai-chat-after-refresh-390x844.png", fullPage: true });

  const viewports = [
    [320, 568], [360, 780], [375, 812], [390, 844], [393, 852], [402, 874], [414, 896], [430, 932],
  ];
  for (const [width, height] of viewports) {
    await page.setViewportSize({ width, height });
    await page.evaluate(() => enterHomeLanding());
    await page.waitForTimeout(180);
    const layout = await page.evaluate(() => {
      const rect = selector => {
        const node = document.querySelector(selector);
        const r = node.getBoundingClientRect();
        return { top: r.top, bottom: r.bottom, left: r.left, right: r.right, width: r.width, height: r.height };
      };
      const canvas = document.querySelector("#neuralCanvas");
      const pixels = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data;
      let sphereInk = 0;
      for (let i = 0; i < pixels.length; i += 4) {
        if (pixels[i + 3] > 12 && (pixels[i] > 80 || pixels[i + 1] > 100 || pixels[i + 2] > 150)) sphereInk++;
      }
      return {
        sphereInk,
        viewportWidth: innerWidth,
        viewportHeight: innerHeight,
        documentWidth: document.documentElement.scrollWidth,
        core: rect(".core-stage"),
        composer: rect("#composer"),
        header: rect(".topbar"),
        quick: rect(".quick-actions"),
        home: rect(".home-intro"),
        recent: rect(".recent-feed"),
        today: rect(".today-panel"),
        cards: [...document.querySelectorAll(".quick-action")].map(node => {const r=node.getBoundingClientRect();return {width:r.width,height:r.height,scrollHeight:node.scrollHeight,clientHeight:node.clientHeight}}),
        controls: ["#attachmentButton","#sendButton","#micButton"].map(selector => rect(selector)),
      };
    });
    assert.ok(layout.documentWidth <= layout.viewportWidth, "horizontal overflow at " + width + "x" + height);
    assert.ok(layout.core.width > 0 && layout.core.height > 0, "sphere missing at " + width + "x" + height);
    assert.ok(layout.sphereInk > 90, "mini sphere animation did not repaint after chat at " + width + "x" + height);
    assert.ok(layout.composer.bottom <= layout.viewportHeight + 1, "composer clipped at " + width + "x" + height);
    assert.ok(layout.recent.bottom <= layout.today.top + 1, "Recent overlaps Today at " + width + "x" + height);
    assert.ok(layout.header.left >= -1 && layout.header.right <= layout.viewportWidth + 1, "header clipped at " + width + "x" + height);
    assert.ok(layout.quick.left >= -1 && layout.quick.right <= layout.viewportWidth + 1, "quick actions clipped at " + width + "x" + height);
    assert.ok(layout.cards.length === 4, "four Home cards required");
    assert.ok(layout.cards.every(card => Math.abs(card.height-layout.cards[0].height)<1 && Math.abs(card.width-layout.cards[0].width)<1), "Home card dimensions mismatch at " + width + "x" + height);
    assert.ok(layout.cards.every(card => card.scrollHeight<=card.clientHeight+2), "Home card content clipped at " + width + "x" + height);
    assert.ok(layout.cards.every(card => card.height<=70), "Home cards should stay slim at " + width + "x" + height);
    if(height>520)assert.ok(layout.cards.every(card => card.height<=90), "Home cards became oversized at " + width + "x" + height);
    assert.ok(layout.composer.width<=layout.home.width-6, "composer not compact at " + width + "x" + height);
    assert.ok(layout.composer.left>=-1 && layout.composer.right<=layout.viewportWidth+1, "composer clips horizontally at " + width + "x" + height);
    assert.ok(layout.controls.filter(control => control.width>0).every(control => control.width>=43 && control.height>=43), "composer action hit targets too small at " + width + "x" + height);
    assert.ok(layout.composer.height>=47 && layout.composer.height<=50, "composer is too tall at " + width + "x" + height);
    if (width === 320) {
      await page.screenshot({ path: "artifacts/personal-ai-home-320x568.png", fullPage: true });
      await page.click("#historyButton");
      await page.waitForFunction(() => document.querySelector("#appDrawer").getBoundingClientRect().left >= -1);
      const narrowSidebar = await page.evaluate(() => ({
        screenWidth:innerWidth, screenHeight:innerHeight,
        aside:document.querySelector("#appDrawer").getBoundingClientRect(),
        footer:document.querySelector("#sidebarAccountButton").getBoundingClientRect(),
        newChat:document.querySelector("#sidebarNewChat").getBoundingClientRect(),
      }));
      assert.ok(narrowSidebar.aside.left >= -1 && narrowSidebar.aside.right <= narrowSidebar.screenWidth + 1, "sidebar must not clip at 320px");
      assert.ok(narrowSidebar.footer.bottom <= narrowSidebar.screenHeight + 1, "account footer must remain accessible at 320x568");
      assert.ok(narrowSidebar.newChat.height >= 44, "new chat must preserve touch target on narrow screens");
      await page.screenshot({ path: "artifacts/personal-ai-sidebar-320x568.png", fullPage: true });
      await page.click("#closeAppDrawer");
      await page.click("#ownerButton");
      await page.waitForFunction(() => {
        const r=document.querySelector("#conversationDrawer").getBoundingClientRect();
        return r.left>=0 && Math.abs(r.right-innerWidth)<=1;
      });
      await page.locator("#conversationDrawer").evaluate(async node=>{await Promise.all(node.getAnimations().map(animation=>animation.finished.catch(()=>{})))});
      const right320=await page.evaluate(()=>({
        width:innerWidth,
        drawer:document.querySelector("#conversationDrawer").getBoundingClientRect(),
        back:{width:document.querySelector("#closeDrawer").offsetWidth},
        search:document.querySelector("#conversationSearch").getBoundingClientRect(),
      }));
      assert.ok(right320.drawer.left>=0 && right320.drawer.right<=right320.width+1,"right Conversations must not clip at 320px");
      assert.ok(right320.back.width>=44 && right320.search.width>180,"right Conversations controls must remain usable at 320px: "+JSON.stringify(right320));
      await page.waitForFunction(()=>document.querySelectorAll(".timeline-entry").length>=10);
      const filters320=await page.locator(".conversation-filters").evaluate(node=>({scroll:node.scrollWidth,width:node.clientWidth,overflow:getComputedStyle(node).overflowX}));
      assert.ok(filters320.scroll>filters320.width&&filters320.overflow==="auto","all timeline categories must remain horizontally scrollable at 320px");
      await page.screenshot({ path: "artifacts/personal-ai-conversations-right-320x568.png", fullPage: true });
      await page.click("#closeDrawer");
    }
    if (width === 430) {
      await page.screenshot({ path: "artifacts/personal-ai-home-430x932.png", fullPage: true });
      await page.click("#historyButton");
      assert.ok(await page.locator("#sidebarAccountButton").isVisible());
      await page.screenshot({ path: "artifacts/personal-ai-sidebar-430x932.png", fullPage: true });
      await page.click("#closeAppDrawer");
    }
  }

  // Keyboard and creation controls use the existing application bindings.
  await page.setViewportSize({ width: 390, height: 844 });
  await page.click("#historyButton");
  await page.click("#sidebarNewChat");
  await page.waitForFunction(() => document.querySelector("#appDrawer").classList.contains("hidden") && !document.body.classList.contains("home-landing") && document.querySelectorAll("#messageStream .message").length === 0);
  await page.click("#historyButton");
  await page.click("#appConversations");
  await page.click("#historyNew");
  await page.waitForFunction(() => !document.body.classList.contains("home-landing") && document.querySelectorAll("#messageStream .message").length === 0);

  // Collapsed one-line pill expands on focus, and its action icons move to the bottom row.
  await page.locator("#message").focus();
  assert.ok(await page.locator("#composer").evaluate(node => node.classList.contains("is-expanded")), "focus must expand the composer even before typing");
  const emptyExpanded = await page.evaluate(() => ({
    composer: document.querySelector("#composer").getBoundingClientRect(),
    editor: document.querySelector("#message").getBoundingClientRect(),
    attach: document.querySelector("#attachmentButton").getBoundingClientRect(),
    mic: document.querySelector("#micButton").getBoundingClientRect(),
  }));
  assert.ok(emptyExpanded.composer.height >= 105, "focused composer must extend upward");
  assert.ok(emptyExpanded.attach.top >= emptyExpanded.editor.bottom - 3 && emptyExpanded.mic.top >= emptyExpanded.editor.bottom - 3, "attachment and microphone must move below the editor");
  await page.locator("#historyButton").focus();
  await page.waitForFunction(() => !document.querySelector("#composer").classList.contains("is-expanded"));
  assert.ok(await page.locator("#composer").evaluate(node => node.getBoundingClientRect().height <= 54), "empty unfocused composer must collapse to the small SMS bar");
  await page.fill("#message", "Hello from browser QA");
  assert.ok(await page.locator("#composer").evaluate(node => node.classList.contains("has-text")), "text input must show send state");
  assert.ok(await page.locator("#sendButton").isVisible(), "send control must appear when typing");

  assert.equal(await page.locator("#micButton").isVisible(), false, "mic icon must yield to send while typing");
  const typedLayout = await page.evaluate(() => ({
    viewportHeight: innerHeight,
    form: document.querySelector("#composer").getBoundingClientRect(),
    editor: document.querySelector("#message").getBoundingClientRect(),
    plus: document.querySelector("#attachmentButton").getBoundingClientRect(),
    send: document.querySelector("#sendButton").getBoundingClientRect(),
  }));
  assert.ok(typedLayout.plus.top >= typedLayout.editor.bottom - 3 && typedLayout.send.top >= typedLayout.editor.bottom - 3, "typing must place attachment and send on the lower toolbar");
  assert.ok(typedLayout.form.bottom <= typedLayout.viewportHeight + 1, "expanded composer must remain visible when focused");
  const singleLineEditorHeight = typedLayout.editor.height;
  await page.fill("#message", "First line\nSecond line\nThird line\nFourth line");
  const multiline = await page.evaluate(() => ({
    viewportHeight: innerHeight,
    form: document.querySelector("#composer").getBoundingClientRect(),
    editor: document.querySelector("#message").getBoundingClientRect(),
    text: document.querySelector("#message").value,
    plus: document.querySelector("#attachmentButton").getBoundingClientRect(),
    send: document.querySelector("#sendButton").getBoundingClientRect(),
  }));
  assert.ok(multiline.editor.height > singleLineEditorHeight + 20, "multiline text must expand the editor vertically");
  assert.ok(multiline.plus.top >= multiline.editor.bottom - 3 && multiline.send.top >= multiline.editor.bottom - 3, "icons must remain in the bottom row with multiple lines");
  assert.ok(multiline.form.bottom <= multiline.viewportHeight + 1, "multiline editor must not push the composer off-screen");
  await page.locator("#message").press("Shift+Enter");
  assert.ok((await page.locator("#message").inputValue()).endsWith("\n"), "Shift+Enter must insert a new line instead of submitting");
  await page.setViewportSize({ width: 320, height: 568 });
  await page.waitForTimeout(100);
  const narrowTyping = await page.evaluate(() => ({
    width: innerWidth,viewportHeight:innerHeight,
    scrollWidth: document.documentElement.scrollWidth,
    form: document.querySelector("#composer").getBoundingClientRect(),
    editor: document.querySelector("#message").getBoundingClientRect(),
    plus: document.querySelector("#attachmentButton").getBoundingClientRect(),
    send: document.querySelector("#sendButton").getBoundingClientRect(),
  }));
  assert.ok(narrowTyping.scrollWidth <= narrowTyping.width, "expanded 320px composer must not overflow horizontally");
  assert.ok(narrowTyping.form.bottom <= narrowTyping.viewportHeight + 1 && narrowTyping.form.left >= -1 && narrowTyping.form.right <= narrowTyping.width + 1, "expanded 320px composer must remain inside viewport");
  assert.ok(narrowTyping.plus.top >= narrowTyping.editor.bottom - 3 && narrowTyping.send.top >= narrowTyping.editor.bottom - 3, "320px toolbar buttons must stay under the editor");
  await page.screenshot({ path: "artifacts/personal-ai-expanded-composer-320x568.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.fill("#message", "Hello from browser QA");
  assert.equal(await page.locator("#homeIntro").isVisible(), false, "new empty chat must not duplicate Home quick actions");
  assert.equal(await page.locator(".core-stage").evaluate(node => getComputedStyle(node).visibility), "visible", "new empty chat retains mini header sphere");
  await page.screenshot({ path: "artifacts/personal-ai-new-chat-390x844.png", fullPage: true });
  await page.locator("#message").focus();
  assert.equal(await page.locator("#message").evaluate(node => document.activeElement === node), true, "composer input must receive keyboard focus");
  await page.locator("#attachmentInput").setInputFiles({ name: "browser-qa.txt", mimeType: "text/plain", buffer: Buffer.from("Browser attachment test") });
  await page.waitForFunction(() => document.querySelector("#toast")?.textContent.includes("Document added to Knowledge"));
  assert.equal(uploadedDocuments.length, 1, "attachment must use the existing Knowledge ingestion endpoint");
  assert.equal(uploadedDocuments[0].filename, "browser-qa.txt");
  assert.ok(uploadedDocuments[0].content_base64, "attachment bytes must be sent to Knowledge");
  await page.click("#sendButton");
  await page.waitForFunction(() => document.querySelectorAll("#messageStream .message").length === 2);
  assert.ok((await page.locator("#messageStream").innerText()).includes("Hello from browser QA"), "user message must render");
  assert.ok((await page.locator("#messageStream").innerText()).includes("Received: Hello from browser QA"), "assistant response must render");
  assert.equal(conversationCreateCount,1,"the first Home/New Chat message must create exactly one fresh conversation");
  assert.deepEqual(turnConversationIds,["new"],"the first message must be sent to the newly created conversation, never the old active chat");
  assert.equal(await page.evaluate(() => currentConversationId),"new","the UI must remain inside the newly created conversation");
  assert.equal(await page.locator(".message-time").count(),2,"canonical timestamps must render for both sides of the first turn");
  assert.equal(await page.locator(".message-time.pending").count(),0,"canonical sync must replace optimistic Syncing timestamps");
  await page.waitForFunction(() => document.querySelector("#composer").getBoundingClientRect().height <= 54);
  await page.fill("#message", "Keyboard submit");
  await page.locator("#message").press("Enter");
  await page.waitForFunction(() => document.querySelectorAll("#messageStream .message").length === 4);
  assert.ok((await page.locator("#messageStream").innerText()).includes("Received: Keyboard submit"), "Enter must submit the multiline editor without requiring a click");
  assert.equal(conversationCreateCount,1,"subsequent messages must reuse the same newly created conversation");
  assert.deepEqual(turnConversationIds,["new","new"],"every later turn must stay in that newly created conversation");
  assert.equal(await page.evaluate(() => currentConversationId),"new");
  assert.equal(await page.locator(".message-time").count(),4,"every canonical user and AI message must keep an individual timestamp");
  assert.equal(await page.locator(".message-time.pending").count(),0);
  // Let the headless browser's synthetic TTS attempt settle, then capture the
  // stable text-chat state rather than a transient autoplay-voice warning.
  await page.waitForTimeout(3500);
  await page.evaluate(()=>{
    if(document.activeElement&&document.activeElement.blur)document.activeElement.blur();
    $('voiceAlert').textContent='';setState('idle');document.querySelector('#toast')?.classList.add('hidden');
  });
  await page.waitForFunction(()=>document.querySelector("#composer").getBoundingClientRect().height<=54);
  await page.screenshot({ path: "artifacts/personal-ai-chat-short-390x844.png", fullPage: true });

  await page.setViewportSize({ width: 844, height: 390 });
  await page.evaluate(() => enterHomeLanding());
  await page.waitForTimeout(250);
  const landscape = await page.evaluate(() => ({
    innerWidth, innerHeight,
    scrollWidth: document.documentElement.scrollWidth,
    composerBottom: document.querySelector("#composer").getBoundingClientRect().bottom,
    headerLeft: document.querySelector(".topbar").getBoundingClientRect().left,
    headerRight: document.querySelector(".topbar").getBoundingClientRect().right,
  }));
  assert.ok(landscape.scrollWidth <= landscape.innerWidth, "landscape must not scroll horizontally");
  assert.ok(landscape.composerBottom <= landscape.innerHeight + 1, "landscape composer must stay in viewport");
  assert.ok(landscape.headerLeft >= 0 && landscape.headerRight <= landscape.innerWidth + 1, "landscape header must fit");
  await page.screenshot({ path: "artifacts/personal-ai-home-landscape-844x390.png", fullPage: true });
  assert.equal(await page.locator("#chatMenuButton").isVisible(),false,"conversation actions must disappear on Home even when old chat exists");
  await page.setViewportSize({width:390,height:844});
  await page.evaluate(()=>openConversation("new"));
  await page.waitForFunction(()=>!document.querySelector("#chatMenuButton").classList.contains("hidden"));
  await page.click("#chatMenuButton");
  await page.click("#chatDelete");
  await audit(page,'Delete confirmation');
  await page.screenshot({path:'artifacts/personal-ai-confirmation-390x844.png',fullPage:true});
  await page.click("#uiDialogCancel");
  assert.deepEqual(deletedConversationIds,[],"cancel must leave conversation untouched");
  await page.click("#chatMenuButton");
  await page.click("#chatDelete");
  await page.click("#uiDialogAccept");
  await page.waitForFunction(()=>document.body.classList.contains("home-landing")&&document.querySelector("#chatMenuButton").classList.contains("hidden"));
  assert.deepEqual(deletedConversationIds,["new"],"confirmed delete must call the secured conversation endpoint exactly once");

  // Product-wide responsive qualification, using API fixtures only in tests.
  await page.setViewportSize({width:390,height:844});
  await page.evaluate(()=>openModule('activities'));
  assert.equal(await page.locator('.activity-stat-grid article').count(),3,'Activities must show the three canonical counts');
  assert.equal((await page.locator('.activity-stat-grid article').nth(0).innerText()).includes('1'),true,'Activities total must derive from the audit response');
  assert.match(await page.locator('.activity-record').innerText(),/Workflow run completed/i,'canonical audit action should have a readable title');
  assert.match(await page.locator('.activity-record').innerText(),/Completed/,'canonical completion state must remain explicit');
  assert.equal(await page.locator('[data-filter-group="activitiesFilters"]').count(),6,'Activities exposes each approved category filter');
  await page.fill('#activitiesSearch','Morning operations');
  assert.equal(await page.locator('.activity-record').count(),1,'Activities search uses safe structured metadata');
  await page.fill('#activitiesSearch','no matching title');
  assert.match(await page.locator('.activity-history').innerText(),/No matching activities/,'Activities search has a useful empty state');
  await page.fill('#activitiesSearch','');
  await page.locator('[data-filter-group="activitiesFilters"][data-filter="workflows"]').click();
  assert.equal(await page.locator('.activity-record').count(),1,'Workflow filter uses canonical workflow audit fields');
  await page.locator('#activityRefresh').click();
  await page.waitForFunction(()=>document.querySelector('.activity-record'));
  await audit(page,'Activities');
  await page.screenshot({path:'artifacts/personal-ai-activities-390x844.png',fullPage:true});
  await page.evaluate(()=>openModule('knowledge'));
  assert.match(await page.locator('.knowledge-record').innerText(),/Owner upload/,'Knowledge row preserves safe source provenance');
  assert.match(await page.locator('.knowledge-record').innerText(),/Indexed · 2 sections/,'Knowledge indexing state derives from persisted index chunks');
  await page.fill('#knowledgeSearch','notes');
  await page.waitForTimeout(360);
  assert.equal(await page.evaluate(()=>document.activeElement?.id),'knowledgeSearch','Knowledge search retains focus after refreshed results render');
  assert.equal(await page.locator('#knowledgeSearch').inputValue(),'notes');
  await audit(page,'Knowledge');
  await page.screenshot({path:'artifacts/personal-ai-knowledge-390x844.png',fullPage:true});
  await page.getByRole('button',{name:'Go back'}).click();
  assert.equal(await page.locator('#modulePanel').isVisible(),true,'section Back must return through application navigation');
  await page.locator('[data-section-close]').click();
  assert.equal(await page.locator('#modulePanel').isVisible(),false,'section Close returns to Home');
  await page.evaluate(()=>openModule('memory'));
  await page.fill('#memorySearch','project');
  await page.waitForTimeout(360);
  assert.equal(await page.evaluate(()=>document.activeElement?.id),'memorySearch','Memory search retains focus after refreshed results render');
  assert.equal(await page.locator('#memorySearch').inputValue(),'project');
  await page.evaluate(()=>openModule('home'));
  const productViewports=[[320,568],[360,800],[375,812],[390,844],[393,852],[430,932],[768,1024],[820,1180],[1024,768],[1280,800],[1440,900]];
  for(const [width,height] of productViewports){
    await page.setViewportSize({width,height});
    for(const name of ['memory','knowledge','activities','devices','workflows','tools','dashboard','settings','system']){
      await page.evaluate(name=>openModule(name),name);
      assert.equal(await page.locator('#modulePanel').isVisible(),true,name+' must render');
      assert.doesNotMatch(await page.locator('#moduleBody').innerText(),/Unable to load this section/,name+' API fixture must render successfully');
      const dimensions=await page.evaluate(()=>({w:innerWidth,scroll:document.documentElement.scrollWidth,body:$('moduleBody').getBoundingClientRect().toJSON()}));
      assert.ok(dimensions.scroll<=dimensions.w,name+' overflows '+width);
      assert.ok(dimensions.body.width>0&&dimensions.body.height>0,name+' has no usable content region '+width);
      if(width===390)await audit(page,name);
      if(width===320&&name==='knowledge'){const search=await page.locator('#knowledgeSearch').boundingBox(),panel=await page.locator('#moduleBody').boundingBox();assert.ok(search.width>=panel.width-4,'Knowledge search must use available mobile width without clipping')}
      if(width===390&&name==='workflows'){assert.equal(await page.locator('#moduleBody h2').filter({hasText:/^Workflows$/}).count(),0,'Workflows body must not repeat its page heading')}
      if([320,390,820,1440].includes(width))await page.screenshot({path:`artifacts/personal-ai-${name}-${width}x${height}.png`,fullPage:true});
    }
    await page.evaluate(()=>openModule('home'));
    assert.ok(await page.locator('#composer').isVisible(),'Home composer must survive module switching');
  }
  await page.setViewportSize({width:390,height:844});
  await page.evaluate(()=>openModule('memory'));
  const emptyGraph=await page.evaluate(()=>drawMemoryGraph({nodes:[],edges:[]}));assert.match(emptyGraph,/No memory relationships yet/);assert.doesNotMatch(emptyGraph,/<svg/,'empty graph must use readable text instead of tiny SVG labels');
  await page.click('#memoryGraph');await page.waitForSelector('.graph-view');
  await audit(page,'Memory graph');
  await page.screenshot({path:'artifacts/personal-ai-memory-graph-390x844.png',fullPage:true});
  await page.click('#memoryTree');await page.waitForSelector('.tree-branch');
  await audit(page,'Memory tree');
  await page.screenshot({path:'artifacts/personal-ai-memory-tree-390x844.png',fullPage:true});
  await page.evaluate(()=>openModule('settings'));
  await page.evaluate(()=>renderSettingsIndex());assert.equal(await page.locator('.settings-index h2').count(),0,'Settings category list must not duplicate the page heading');
  for(const section of ['personal','voice','models','memory','apps','approvals','devices','notifications','data','security','system','advanced']){
    await page.evaluate(section=>renderSettings(section),section);
    assert.ok(await page.locator('.settings-content h2').count(),section+' must have a settings heading');
    await audit(page,'Settings '+section);
  }
  await page.evaluate(()=>openModule('home'));

  memoryMode='loading';
  await page.evaluate(()=>{void openModule('memory')});
  await page.waitForSelector('.ui-skeleton');
  await page.screenshot({path:'artifacts/personal-ai-loading-390x844.png',fullPage:true});
  memoryMode='ready';releaseMemory();
  await page.waitForSelector('#memorySearch');
  for(const mode of ['permission','failure']){
    memoryMode=mode;await page.evaluate(()=>openModule('memory'));
    assert.doesNotMatch(await page.locator('#moduleBody').innerText(),/Internal trace/);
    assert.match(await page.locator('#moduleBody').innerText(),mode==='permission'?/permission/:/Unable to load/);
    await audit(page,'Memory '+mode);
    await page.screenshot({path:`artifacts/personal-ai-${mode}-390x844.png`,fullPage:true});
    memoryMode='ready';await page.click('#moduleBody .ui-button');await page.waitForSelector('#memorySearch');
  }
  await page.evaluate(()=>openModule('home'));

  // Signing out clears previously loaded private rows, and the drawer must not
  // leave an unauthorized request stuck in its loading state.
  revokeSession=true;
  await page.click("#historyButton");
  await page.click("#sidebarAccountButton");
  await page.click("#drawerSignOut");
  await page.click("#uiDialogAccept");
  await page.waitForFunction(()=>!document.querySelector("#enrollPanel").classList.contains("hidden"));
  await page.click("#ownerButton");
  await page.waitForFunction(()=>document.querySelector("#conversationCount").textContent==="Sign in required");
  assert.match(await page.locator("#conversationList").innerText(),/Sign in to view your conversations, plans, and activity\./);
  assert.doesNotMatch(await page.locator("#conversationList").innerText(),/Project Planning|Team planning meeting|Finish daily review/,
    "signed-out timeline must not retain authenticated conversation or activity rows");
  assert.equal(await page.locator("#recentList .recent-feed-row").count(),0,"sign-out must clear the Recent feed");
  assert.equal(await page.locator("#historyList .history-row").count(),0,"sign-out must clear the independent history panel");
  assert.doesNotMatch(await page.locator("#conversationList").innerText(),/Loading your timeline|Loading real Personal AI activity/,
    "signed-out timeline must not spin indefinitely");
  await page.screenshot({path:"artifacts/personal-ai-signed-out-timeline-390x844.png",fullPage:true});

  // Authentication presentation only: real password, Google and passkey authority
  // are exercised separately by the server integration/security suite.
  const locked = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: engine!=="firefox", hasTouch: true, serviceWorkers:"block" });
  await locked.route("https://accounts.google.com/**", route => route.abort());
  await locked.route("**/iphone/api/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/status")) {
      return route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ detail: "Owner verification required" }) });
    }
    return route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({ password_available: true, passkey_available: false, google_available: false }),
    });
  });
  await locked.goto("http://127.0.0.1:4173/iphone/", { waitUntil: "domcontentloaded" });
  await locked.waitForFunction(() => !document.querySelector("#enrollPanel").classList.contains("hidden"));
  assert.ok(await locked.locator("#passwordChoice").isVisible(), "real owner password option must remain accessible");
  await locked.click("#passwordChoice");
  assert.ok(await locked.locator("#ownerPassword").isVisible(), "owner password form must open");
  await audit(locked,"login-390x844");
  await locked.screenshot({ path: "artifacts/personal-ai-login-390x844.png", fullPage: true });
  await locked.close();

  assert.deepEqual(pageErrors, [], "page must render without uncaught JavaScript errors");
  await (await import('node:fs/promises')).writeFile('artifacts/pwa-verification.json',JSON.stringify({fixtureData:true,engine,viewports:productViewports,accessibility:auditResults,longThreadPerformance,uncaughtErrors:pageErrors},null,2));
  console.log("Right unified timeline passed chats, meetings, work, reminders, workflow, done and authorized audit filters, chronological ordering, search, completion, Back, New chat, Plan and eleven viewports.");
} finally {
  await browser.close();
}
