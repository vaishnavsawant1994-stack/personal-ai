import assert from "node:assert/strict";
import { chromium } from "playwright";

const browser = await chromium.launch({ headless: true });

const conversations = [
  { id: "c1", title: "Project Planning", preview: "Continue planning the project", updated_at: "2026-09-30T12:30:00+05:30" },
  { id: "c2", title: "Mushroom Farm Plan", preview: "Shed layout and capacity", updated_at: "2026-09-30T10:15:00+05:30" },
  { id: "c3", title: "Onion Cultivation Guide", preview: "Irrigation and fertilizer plan", updated_at: "2026-09-29T09:42:00+05:30" },
];

const activeConversation = {
  thread: { id: "c1", title: "Project Planning", updated_at: conversations[0].updated_at },
  events: [
    { kind: "user_message", payload: { text: "Plan mushroom farm shed layout with complete details" } },
    { kind: "assistant_message", payload: { text: "I can help with the shed layout, rack design, climate control, and cost planning." } },
  ],
};

try {
  const page = await browser.newPage({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
  });

  const pageErrors = [];
  const uploadedDocuments = [];
  page.on("pageerror", error => pageErrors.push(error.message));

  await page.route("**/iphone/api/**", route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace("/iphone/api", "");
    const method = request.method();

    let body = {};
    if (path === "/status") {
      body = { model: { state: "ready" }, conversations, conversation: null, memory_count: 3 };
    } else if (path === "/preferences") {
      body = { continuous_voice: true, voice_rate: 1, quiet_hours: true };
    } else if (path.startsWith("/conversations/c1/activate")) {
      body = activeConversation;
    } else if (path.startsWith("/conversations/c1")) {
      body = activeConversation;
    } else if (path.startsWith("/conversations") && method === "GET") {
      const q = (url.searchParams.get("q") || "").toLowerCase();
      body = { conversations: conversations.filter(item => item.title.toLowerCase().includes(q)) };
    } else if (path === "/conversations" && method === "POST") {
      body = { thread: { id: "new", title: "New conversation", updated_at: new Date().toISOString() }, events: [] };
    } else if (path === "/voice/turn" && method === "POST") {
      const text = JSON.parse(request.postData() || "{}").transcript;
      body = { status: "ok", conversation_id: "new", conversation_title: "New conversation", reply: "Received: " + text };
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
    recent: [...document.querySelectorAll("#recentList .recent-row strong")].map(node => node.textContent),
    headerSphere: Boolean(document.querySelector(".topbar #neuralCanvas")),
    headerGreenDot: Boolean(document.querySelector(".topbar .status-dot")),
    actionTitles: [...document.querySelectorAll(".quick-action strong")].map(node => node.textContent),
    cardRects: [...document.querySelectorAll(".quick-action")].map(node => { const r=node.getBoundingClientRect(); return {width:r.width,height:r.height} }),
    homeWidth: document.querySelector(".home-intro").getBoundingClientRect().width,
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth,
    innerHeight,
  }));
  assert.equal(homeState.bottomNavPresent, false, "persistent bottom navigation must be removed");
  assert.equal(homeState.quickActions.length, 4, "home must expose four real quick actions");
  assert.deepEqual(homeState.actionTitles, ["Chat", "Create", "Imagine", "Tools"]);
  assert.ok(homeState.cardRects.every(card => Math.abs(card.height-homeState.cardRects[0].height)<1 && Math.abs(card.width-homeState.cardRects[0].width)<1), "four Home cards must be exactly equal sized");
  assert.ok(homeState.composer.width <= homeState.homeWidth-10, "Home composer must be narrower than the cards");
  assert.ok(homeState.cardRects.every(card => card.height <= 90), "Home tiles must remain the SMALL original card size");
  assert.ok(homeState.composer.height >= 50 && homeState.composer.height <= 54, "Home composer must be compact, close to an SMS field");
  assert.equal(await page.locator("#sendButton").isVisible(), false, "idle composer must show microphone, not inactive send");
  assert.equal(await page.locator("#micButton").isVisible(), true, "idle composer microphone must remain available");
  assert.equal(await page.locator("#attachmentButton svg path").getAttribute("d"), "M12 5v14M5 12h14", "attachment icon must be a compact plus");
  assert.equal(await page.locator("#attachmentButton").getAttribute("aria-label"), "Add a document", "compact plus must retain the accessible attachment label");
  assert.equal(homeState.headerSphere, true, "original sphere must occupy compact top header");
  assert.equal(homeState.headerGreenDot, false, "top status dot must be removed");
  assert.deepEqual(homeState.recent, conversations.map(c => c.title), "Recent must show real conversation data");
  assert.equal(await page.locator(".prompt-chips, [data-prompt]").count(), 0, "bottom suggestion strip must be fully removed");
  assert.ok(homeState.menuButton.width >= 44 && homeState.menuButton.height >= 44, "hamburger target must be at least 44px");
  assert.ok(homeState.core.width > 0 && homeState.core.height > 0, "sphere must remain visible on Home");
  assert.ok(homeState.composer.bottom <= homeState.innerHeight + 1, "composer must remain inside the viewport");
  assert.ok(homeState.scrollWidth <= homeState.innerWidth, "home must not scroll horizontally");
  await page.screenshot({ path: "artifacts/personal-ai-home-390x844.png", fullPage: true });

  // Owner Controls remain reachable through the hamburger (top-right icon now opens Recent).
  await page.click("#historyButton");
  await page.click("#appOwnerControls");
  await page.waitForFunction(() => !document.querySelector("#ownerMenu").classList.contains("hidden"));
  for (const item of ["Settings", "Trusted devices", "System status", "Sign out this browser"]) {
    assert.ok((await page.locator("#ownerMenu").innerText()).includes(item), "Owner Controls missing " + item);
  }
  await page.screenshot({ path: "artifacts/personal-ai-owner-controls-390x844.png", fullPage: true });
  await page.keyboard.press("Escape");
  await page.waitForFunction(() => document.querySelector("#ownerMenu").classList.contains("hidden"));

  await page.click("#historyButton");
  await page.waitForFunction(() => !document.querySelector("#appDrawer").classList.contains("hidden"));
  const drawerState = await page.evaluate(() => ({
    labels: [...document.querySelectorAll("#appDrawer .drawer-row strong")].map(node => node.textContent.trim()),
    rect: document.querySelector("#appDrawer").getBoundingClientRect(),
    expanded: document.querySelector("#historyButton").getAttribute("aria-expanded"),
  }));
  for (const expected of ["Home", "Conversations", "Memory", "Knowledge", "Activities", "Owner controls", "Settings", "Trusted devices", "System status", "Sign out"]) {
    assert.ok(drawerState.labels.includes(expected), "missing navigation item: " + expected);
  }
  assert.equal(drawerState.expanded, "true", "hamburger aria-expanded must track the drawer");
  assert.ok(drawerState.rect.width <= 390, "drawer must fit mobile viewport");
  await page.screenshot({ path: "artifacts/personal-ai-menu-390x844.png", fullPage: true });

  await page.click("#appConversations");
  await page.waitForFunction(() => !document.querySelector("#conversationDrawer").classList.contains("hidden"));
  await page.waitForFunction(() => document.querySelectorAll(".conversation-item").length === 3);
  const conversationState = await page.evaluate(() => ({
    groups: [...document.querySelectorAll(".conversation-group-title")].map(node => node.textContent.trim()),
    filters: [...document.querySelectorAll(".conversation-filter")].map(node => node.textContent.trim()),
    rows: [...document.querySelectorAll(".conversation-item strong")].map(node => node.textContent.trim()),
    rect: document.querySelector("#conversationDrawer").getBoundingClientRect(),
  }));
  assert.deepEqual(conversationState.filters, ["All", "Recent"], "unsupported favorites/archive filters must not be fabricated");
  assert.ok(conversationState.groups.length >= 1, "real timestamps should produce conversation date grouping");
  assert.deepEqual(conversationState.rows, conversations.map(item => item.title));
  assert.ok(conversationState.rect.width <= 390, "conversation manager must fit viewport");
  await page.screenshot({ path: "artifacts/personal-ai-conversations-390x844.png", fullPage: true });

  await page.fill("#conversationSearch", "Onion");
  await page.waitForFunction(() => {
    const rows = [...document.querySelectorAll(".conversation-item strong")];
    return rows.length === 1 && rows[0].textContent.includes("Onion");
  });
  await page.fill("#conversationSearch", "nonexistent title");
  await page.waitForFunction(() => {
    return !document.querySelector(".conversation-item") && document.querySelector(".conversation-empty")?.textContent.includes("No conversations match");
  });
  await page.fill("#conversationSearch", "");
  await page.waitForFunction(() => document.querySelectorAll(".conversation-item").length === 3);
  await page.click("#closeDrawer");
  await page.waitForFunction(() => document.querySelector("#conversationDrawer").classList.contains("hidden"));
  await page.click("#historyButton");
  await page.click("#appConversations");

  await page.click(".conversation-item");
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
  assert.equal(await page.locator(".state").isVisible(), false, "idle conversations must not show a redundant READY heading");
  assert.equal(chatState.messageCount, 2);
  assert.ok(chatState.messages.height > 0, "active conversation needs a real scroll viewport");
  assert.ok(chatState.composer.bottom <= chatState.innerHeight + 1, "chat composer must remain visible");
  assert.ok(chatState.scrollWidth <= chatState.innerWidth, "active conversation must not overflow horizontally");
  await page.screenshot({ path: "artifacts/personal-ai-chat-390x844.png", fullPage: true });

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
        cards: [...document.querySelectorAll(".quick-action")].map(node => {const r=node.getBoundingClientRect();return {width:r.width,height:r.height,scrollHeight:node.scrollHeight,clientHeight:node.clientHeight}}),
        controls: ["#attachmentButton","#sendButton","#micButton"].map(selector => rect(selector)),
      };
    });
    assert.ok(layout.documentWidth <= layout.viewportWidth, "horizontal overflow at " + width + "x" + height);
    assert.ok(layout.core.width > 0 && layout.core.height > 0, "sphere missing at " + width + "x" + height);
    assert.ok(layout.sphereInk > 90, "mini sphere animation did not repaint after chat at " + width + "x" + height);
    assert.ok(layout.composer.bottom <= layout.viewportHeight + 1, "composer clipped at " + width + "x" + height);
    assert.ok(layout.header.left >= -1 && layout.header.right <= layout.viewportWidth + 1, "header clipped at " + width + "x" + height);
    assert.ok(layout.quick.left >= -1 && layout.quick.right <= layout.viewportWidth + 1, "quick actions clipped at " + width + "x" + height);
    assert.ok(layout.cards.length === 4, "four Home cards required");
    assert.ok(layout.cards.every(card => Math.abs(card.height-layout.cards[0].height)<1 && Math.abs(card.width-layout.cards[0].width)<1), "Home card dimensions mismatch at " + width + "x" + height);
    assert.ok(layout.cards.every(card => card.scrollHeight<=card.clientHeight+2), "Home card content clipped at " + width + "x" + height);
    if(height>520)assert.ok(layout.cards.every(card => card.height<=90), "Home cards became oversized at " + width + "x" + height);
    assert.ok(layout.composer.width<=layout.home.width-6, "composer not compact at " + width + "x" + height);
    assert.ok(layout.composer.left>=-1 && layout.composer.right<=layout.viewportWidth+1, "composer clips horizontally at " + width + "x" + height);
    assert.ok(layout.controls.filter(control => control.width>0).every(control => control.width>=43 && control.height>=43), "composer action hit targets too small at " + width + "x" + height);
    assert.ok(layout.composer.height>=50 && layout.composer.height<=54, "composer is too tall at " + width + "x" + height);
    if (width === 320) await page.screenshot({ path: "artifacts/personal-ai-home-320x568.png", fullPage: true });
    if (width === 430) await page.screenshot({ path: "artifacts/personal-ai-home-430x932.png", fullPage: true });
  }

  // Keyboard and creation controls use the existing application bindings.
  await page.setViewportSize({ width: 390, height: 844 });
  await page.click("#historyButton");
  await page.click("#appConversations");
  await page.click("#newConversation");
  await page.waitForFunction(() => !document.body.classList.contains("home-landing") && document.querySelectorAll("#messageStream .message").length === 0);
  await page.fill("#message", "Hello from browser QA");
  assert.ok(await page.locator("#composer").evaluate(node => node.classList.contains("has-text")), "text input must show send state");
  assert.ok(await page.locator("#sendButton").isVisible(), "send control must appear when typing");
  assert.equal(await page.locator("#micButton").isVisible(), false, "mic icon must yield to send while typing");
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

  // Authentication presentation only: real password, Google and passkey authority
  // are exercised separately by the server integration/security suite.
  const locked = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
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
  await locked.screenshot({ path: "artifacts/personal-ai-login-390x844.png", fullPage: true });
  await locked.close();

  assert.deepEqual(pageErrors, [], "page must render without uncaught JavaScript errors");
  console.log("Original small equal-size Home cards and compact ChatGPT-style composer passed alongside real Recent, navigation, chat, original sphere, and eight viewport checks.");
} finally {
  await browser.close();
}
