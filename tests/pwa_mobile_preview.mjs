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
  assert.ok(canvasInk > 200, "existing neural sphere renderer did not paint");

  const homeState = await page.evaluate(() => ({
    bottomNavPresent: Boolean(document.querySelector(".nav")),
    quickActions: [...document.querySelectorAll(".quick-action")].map(node => node.textContent.replace(/\s+/g, " ").trim()),
    menuButton: document.querySelector("#historyButton").getBoundingClientRect(),
    composer: document.querySelector("#composer").getBoundingClientRect(),
    core: document.querySelector(".core-stage").getBoundingClientRect(),
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth,
    innerHeight,
  }));
  assert.equal(homeState.bottomNavPresent, false, "persistent bottom navigation must be removed");
  assert.equal(homeState.quickActions.length, 4, "home must expose four real quick actions");
  assert.ok(homeState.menuButton.width >= 44 && homeState.menuButton.height >= 44, "hamburger target must be at least 44px");
  assert.ok(homeState.core.width > 0 && homeState.core.height > 0, "sphere must remain visible on Home");
  assert.ok(homeState.composer.bottom <= homeState.innerHeight + 1, "composer must remain inside the viewport");
  assert.ok(homeState.scrollWidth <= homeState.innerWidth, "home must not scroll horizontally");
  await page.screenshot({ path: "artifacts/personal-ai-home-390x844.png", fullPage: true });

  // Capture Owner Controls independently from the hamburger navigation.
  await page.click("#ownerButton");
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
  assert.equal(chatState.coreVisibility, "hidden", "active conversation must conceal Home sphere while retaining its original animation loop");
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
      };
    });
    assert.ok(layout.documentWidth <= layout.viewportWidth, "horizontal overflow at " + width + "x" + height);
    assert.ok(layout.core.width > 0 && layout.core.height > 0, "sphere missing at " + width + "x" + height);
    assert.ok(layout.sphereInk > 200, "sphere animation did not repaint after chat at " + width + "x" + height);
    assert.ok(layout.composer.bottom <= layout.viewportHeight + 1, "composer clipped at " + width + "x" + height);
    assert.ok(layout.header.left >= -1 && layout.header.right <= layout.viewportWidth + 1, "header clipped at " + width + "x" + height);
    assert.ok(layout.quick.left >= -1 && layout.quick.right <= layout.viewportWidth + 1, "quick actions clipped at " + width + "x" + height);
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
  assert.ok(await page.locator("#sendButton").isVisible(), "send control must replace microphone when typing");
  await page.locator("#message").focus();
  assert.equal(await page.locator("#message").evaluate(node => document.activeElement === node), true, "composer input must receive keyboard focus");

  assert.deepEqual(pageErrors, [], "page must render without uncaught JavaScript errors");
  console.log("Final Personal AI mobile redesign passed Home, menu, conversations, chat, sphere preservation, no-bottom-nav, and 8 iPhone viewport checks.");
} finally {
  await browser.close();
}
