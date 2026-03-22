/**
 * TradingView 截图（Playwright + stealth）
 *
 * 两种模式（二选一）：
 * 1) --cdp http://127.0.0.1:9222  连接你已启动的 Chrome（与 Selenium 远程调试同一端口），复用登录态
 * 2) 不传 --cdp                    使用 launchPersistentContext + user_data（独立浏览器，不用 9222）
 *
 * 用法:
 *   node screenshot.js --cdp http://127.0.0.1:9222 --url "https://www.tradingview.com/chart/?symbol=BINANCE:ETHUSDT&interval=15m" --out /abs/path.png
 *
 * 环境变量:
 *   HEADLESS=1           仅对「非 CDP」模式有效
 *   TV_EXTRA_WAIT_MS     图表加载后额外等待
 */
const path = require("path");
const fs = require("fs");
const { setTimeout: sleep } = require("timers/promises");

let chromium;
let StealthPlugin;
try {
  ({ chromium } = require("playwright-extra"));
  StealthPlugin = require("playwright-extra-plugin-stealth");
} catch (e) {
  console.error(
    "[ERROR] 缺少依赖，请在 dealMsg/tv_playwright 目录执行: npm install && npx playwright install chromium"
  );
  console.error(e.message);
  process.exit(1);
}

chromium.use(StealthPlugin());

function parseArgs() {
  const a = process.argv.slice(2);
  const out = { url: "", out: "", timeout: 120000, cdp: "" };
  for (let i = 0; i < a.length; i++) {
    if (a[i] === "--url") out.url = a[++i] || "";
    else if (a[i] === "--out") out.out = a[++i] || "";
    else if (a[i] === "--timeout") out.timeout = parseInt(a[++i] || "120000", 10);
    else if (a[i] === "--cdp") out.cdp = a[++i] || "";
  }
  return out;
}

async function screenshotViaCdp(cdpUrl, url, absOut, timeout) {
  console.error(`[INFO] Playwright 通过 CDP 连接: ${cdpUrl}（复用已打开的 Chrome）`);
  const browser = await chromium.connectOverCDP(cdpUrl);
  const contexts = browser.contexts();
  const context = contexts.length ? contexts[0] : await browser.newContext();
  const page = await context.newPage();
  try {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.goto(url, { waitUntil: "domcontentloaded", timeout });
    await page.waitForSelector("#chart-container", { timeout: 90000 }).catch(() => {
      console.warn("[WARN] #chart-container 未在 90s 内出现，仍尝试截图");
    });
    const extraWait = parseInt(process.env.TV_EXTRA_WAIT_MS || "8000", 10);
    await sleep(Number.isFinite(extraWait) ? extraWait : 8000);
    await page.screenshot({ path: absOut, fullPage: true });
    console.log("[OK]", absOut);
  } finally {
    await page.close().catch(() => {});
    await browser.close();
  }
}

async function screenshotPersistent(url, absOut, timeout) {
  const userDataDir = path.join(__dirname, "user_data");
  fs.mkdirSync(userDataDir, { recursive: true });

  const headless =
    process.env.HEADLESS === "1" || String(process.env.HEADLESS).toLowerCase() === "true";

  const ua =
    process.env.TV_USER_AGENT ||
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36";

  const launchOpts = {
    headless,
    args: [
      "--disable-blink-features=AutomationControlled",
      "--no-sandbox",
      "--disable-dev-shm-usage",
    ],
    viewport: { width: 1920, height: 1080 },
    ignoreHTTPSErrors: true,
    locale: "en-US",
    userAgent: ua,
  };

  if (process.platform === "darwin" || process.platform === "win32") {
    launchOpts.channel = "chrome";
  }

  const context = await chromium.launchPersistentContext(userDataDir, launchOpts);
  const page =
    context.pages().length > 0 ? context.pages()[0] : await context.newPage();

  try {
    await page.goto(url, { waitUntil: "domcontentloaded", timeout });
    await page.waitForSelector("#chart-container", { timeout: 90000 }).catch(() => {
      console.warn("[WARN] #chart-container 未在 90s 内出现，仍尝试截图");
    });
    const extraWait = parseInt(process.env.TV_EXTRA_WAIT_MS || "8000", 10);
    await sleep(Number.isFinite(extraWait) ? extraWait : 8000);
    await page.screenshot({ path: absOut, fullPage: true });
    console.log("[OK]", absOut);
  } finally {
    await context.close();
  }
}

(async () => {
  let { url, out: outPath, timeout, cdp } = parseArgs();
  cdp = cdp || process.env.CHROME_CDP_URL || process.env.DEALMSG_CHROME_CDP_URL || "";

  if (!url || !outPath) {
    console.error(
      "Usage: node screenshot.js [--cdp http://127.0.0.1:9222] --url <tradingview_url> --out <output.png> [--timeout 120000]"
    );
    console.error(
      "  不设 --cdp 时走独立 Chrome（user_data）；设 --cdp 则连接本机已用 --remote-debugging-port 启动的 Chrome。"
    );
    process.exit(2);
  }

  const absOut = path.isAbsolute(outPath) ? outPath : path.resolve(process.cwd(), outPath);
  fs.mkdirSync(path.dirname(absOut), { recursive: true });

  if (cdp) {
    const u = cdp.startsWith("http") ? cdp : `http://${cdp}`;
    await screenshotViaCdp(u, url, absOut, timeout);
  } else {
    await screenshotPersistent(url, absOut, timeout);
  }
})().catch((err) => {
  console.error("[ERROR]", err);
  process.exit(1);
});
