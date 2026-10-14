import { chromium } from "@playwright/test";
const b = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium-1194/chrome-linux/chrome" });
const p = await b.newPage({ viewport: { width: 1400, height: 1000 } });
const errors = [];
p.on("pageerror", (e) => errors.push(e.message));
p.on("console", (m) => m.type() === "error" && errors.push(m.text()));
await p.goto("http://localhost:3000/login");
await p.selectOption("select", "demo-admin");
await p.click("text=Continue");
await p.waitForSelector("h1:has-text('Election overview')");
for (const [path, wait] of [["/", "Data sources"], ["/explorer", "District map"], ["/results", "Most recent"], ["/issues", "Coverage"], ["/polls", "Polls"], ["/forecasts", "Run"], ["/sources", "OpenFEC"], ["/admin", "Members"]]) {
  await p.goto("http://localhost:3000" + path);
  await p.waitForSelector(`text=${wait}`, { timeout: 15000 }).catch(() => errors.push("timeout " + path));
  await p.waitForTimeout(800);
  await p.screenshot({ path: `/tmp/claude-0/shots/${path === "/" ? "overview" : path.slice(1)}.png`, fullPage: false });
}
console.log("errors:", errors);
await b.close();
