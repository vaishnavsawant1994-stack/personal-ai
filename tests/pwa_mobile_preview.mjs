import assert from "node:assert/strict";
import { chromium } from "playwright";

const browser = await chromium.launch({ headless: true });
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
    const isStatus = new URL(route.request().url()).pathname.endsWith("/status");
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(isStatus
        ? { model: { state: "ready" }, conversations: [], conversation: null }
        : {}),
    });
  });
  await page.route("https://accounts.google.com/**", route => route.abort());
  await page.goto("http://127.0.0.1:4173/iphone/", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => !document.querySelector("#voicePanel").classList.contains("hidden"));
  await page.evaluate(() => {
    document.querySelector("#stateLabel").textContent = "Ready";
    document.querySelector("#status").textContent = "Tap the microphone once and speak naturally.";
    const stream = document.querySelector("#messageStream");
    const fixture = [
      ["assistant", "Hi, Vaishnav. I can help answer questions, plan, write, and organize information. What would you like to do today?"],
      ["user", "Can you explain how the whole system works inside you?"],
      ["assistant", "I’m your personal AI. I can help with questions, planning, writing, and your saved knowledge. Ask me about any part, and I’ll explain it clearly."],
    ];
    for (const [role, text] of fixture) {
      const message = document.createElement("div");
      message.className = "message " + role;
      message.textContent = text;
      stream.append(message);
    }
    document.body.classList.add("has-conversation");
    stream.scrollTop = stream.scrollHeight;
  });
  await page.waitForFunction(() => {
    const canvas = document.querySelector("#neuralCanvas");
    return canvas.width > 0 && canvas.height > 0;
  });
  await page.waitForTimeout(500);
  const initialCanvasInk = await page.evaluate(() => {
    const canvas = document.querySelector("#neuralCanvas");
    const pixels = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data;
    let ink = 0;
    for (let i = 0; i < pixels.length; i += 4) {
      if (pixels[i + 3] > 12 && (pixels[i] > 80 || pixels[i + 1] > 100 || pixels[i + 2] > 150)) ink++;
    }
    return ink;
  });
  assert.ok(initialCanvasInk > 200, "neural mesh did not paint at 390x844");
  await page.screenshot({ path: "artifacts/personal-ai-iphone-390x844.png" });

  const checkLayout = async (width, height) => {
    await page.setViewportSize({ width, height });
    await page.waitForTimeout(500);
    if (width === 320) await page.screenshot({ path: "artifacts/personal-ai-iphone-320x568.png" });
    const data = await page.evaluate(() => {
      const rect = selector => {
        const r = document.querySelector(selector).getBoundingClientRect();
        return { top: r.top, bottom: r.bottom, width: r.width, height: r.height };
      };
      const canvas = document.querySelector("#neuralCanvas");
      const pixels = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data;
      let canvasInk = 0;
      for (let i = 0; i < pixels.length; i += 4) {
        if (pixels[i + 3] > 12 && (pixels[i] > 80 || pixels[i + 1] > 100 || pixels[i + 2] > 150)) canvasInk++;
      }
      const visibleLabels = [...document.querySelectorAll(".nav button")]
        .filter(item => item.getBoundingClientRect().width > 0)
        .map(item => item.querySelector("span")?.textContent.trim());
      return {
        canvasInk,
        viewportWidth: innerWidth,
        documentWidth: document.documentElement.scrollWidth,
        core: rect(".core-stage"),
        canvas: rect("#neuralCanvas"),
        messages: rect("#messageStream"),
        composer: rect("#composer"),
        nav: rect(".nav"),
        visibleLabels,
        finalMessageBottom: document.querySelector("#messageStream").lastElementChild?.getBoundingClientRect().bottom ?? 0,
      };
    });
    console.log(`layout diagnostics ${width}x${height}: ${JSON.stringify({data,pageErrors})}`);
    assert.deepEqual(data.visibleLabels, ["Home", "Memory", "Knowledge", "Activities", "More"], `wrong visible nav labels at ${width}x${height}`);
    assert.ok(data.documentWidth <= data.viewportWidth, `horizontal overflow at ${width}x${height}`);
    assert.ok(data.core.height > 0 && data.canvas.height > 0, `Core missing at ${width}x${height}`);
    assert.ok(data.messages.height > 0, `message viewport missing at ${width}x${height}`);
    assert.ok(data.canvasInk > 200, `neural mesh did not repaint after viewport change to ${width}x${height}`);
    assert.ok(data.finalMessageBottom <= data.messages.bottom + 1, `latest message is clipped at ${width}x${height}`);
    assert.ok(data.composer.bottom < data.nav.top, `composer overlaps nav at ${width}x${height}`);
  };
  await checkLayout(320, 568);
  await checkLayout(390, 844);
  await checkLayout(430, 932);
  assert.deepEqual(pageErrors, [], "page must render without uncaught JavaScript errors");
  console.log("PWA mobile layout passed at 320x568, 390x844, and 430x932.");
} finally {
  await browser.close();
}
