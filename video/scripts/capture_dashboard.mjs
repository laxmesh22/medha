// Capture the Auri clinician dashboard (demo data) for the intro video: 2x screenshots of each screen plus the
// on-screen rectangles of the controls the video points at. Needs the dev server (npm --prefix clinician run dev).
//   node video/scripts/capture_dashboard.mjs <chrome-headless-shell.exe> [outDir]
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";

const CHROME = process.argv[2];
const OUT = process.argv[3] ?? "video/public/intro";
const BASE = "http://localhost:5175";
const W = 1440;
const H = 810;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
mkdirSync(OUT, { recursive: true });

const chrome = spawn(CHROME, ["--headless", "--disable-gpu", "--hide-scrollbars", "--remote-debugging-port=9334",
  `--window-size=${W},${H}`, "about:blank"], { stdio: "ignore" });
const rects = {};
let ws;
try {
  let list = [];
  for (let i = 0; i < 40 && !list.length; i++) {
    try { list = await (await fetch("http://127.0.0.1:9334/json/list")).json(); } catch { /* starting */ }
    await sleep(250);
  }
  ws = new WebSocket(list.find((t) => t.type === "page").webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener("open", r, { once: true }));
  let id = 0;
  const pending = new Map();
  ws.addEventListener("message", (m) => {
    const d = JSON.parse(m.data);
    if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); }
  });
  const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
  const run = async (expr) => {
    const r = await send("Runtime.evaluate", { expression: `(async () => { ${expr} })()`, awaitPromise: true, returnByValue: true });
    if (r.result?.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails).slice(0, 400));
    return r.result?.result?.value;
  };
  const size = (h) => send("Emulation.setDeviceMetricsOverride", { width: W, height: h, deviceScaleFactor: 2, mobile: false });
  const shot = async (name, h = H) => {
    await size(h);
    await sleep(600);
    const r = await send("Page.captureScreenshot", { format: "png" });
    writeFileSync(`${OUT}/${name}.png`, Buffer.from(r.result.data, "base64"));
    console.log("shot", name, h);
  };
  const find = (text, sel) => `[...document.querySelectorAll(${JSON.stringify(sel)})].find(e => e.textContent.trim().startsWith(${JSON.stringify(text)}) || e.title === ${JSON.stringify(text)})`;
  const rect = async (key, text, sel = "button, a") => {
    rects[key] = await run(`const el = ${find(text, sel)}; if (!el) throw new Error("no " + ${JSON.stringify(text)});
      const b = el.getBoundingClientRect(); return { x: b.x, y: b.y, w: b.width, h: b.height };`);
  };
  const click = async (text, sel = "button, a") => {
    await run(`const el = ${find(text, sel)}; if (!el) throw new Error("no " + ${JSON.stringify(text)}); el.click(); return true;`);
    await sleep(800);
  };
  const go = async (path) => {
    await run(`window.history.pushState({}, "", ${JSON.stringify(path)}); window.dispatchEvent(new PopStateEvent("popstate")); return true;`);
    await sleep(900);
  };

  await send("Page.enable");
  await size(H);
  await send("Page.navigate", { url: BASE + "/" });
  await sleep(2500);
  await run(`try { localStorage.clear(); } catch {} return true;`);
  await send("Page.navigate", { url: BASE + "/" });
  await sleep(2500);

  // signed in as the demo physiotherapist
  await shot("overview", 1250);
  await rect("ov_attention", "Needs attention", "h2");
  await rect("ov_calls", "Video calls", "h2");
  await go("/patients");
  await shot("patients");
  await go("/patients/p-meera");
  await shot("progress", 1640);
  await rect("pr_rom", "Range of motion", "h2");
  await go("/patients/p-meera?tab=plan");
  await shot("plan");
  await rect("plan_edit", "Edit plan");
  await click("Edit plan");
  await run(`const el = document.querySelector('input[aria-label="Reps"]'); const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    set.call(el, "12"); el.dispatchEvent(new Event("input", { bubbles: true })); return true;`);
  await sleep(300);
  await shot("plan_edit");
  await rect("plan_reps", "", "input[aria-label=\"Reps\"]");
  await rect("plan_publish", "Publish version");
  await click("Publish version");
  await shot("plan_v2");
  await go("/patients/p-arjun?tab=video");
  await shot("video", 1000);
  await rect("vid_start", "Start video call");
  await rect("vid_join", "Join");
  await go("/profile");
  await shot("profile");
  await rect("pf_code", "Copy code");

  // sign out, then a new doctor signs up
  await click("Sign out");
  await shot("login");
  await rect("lg_google", "Continue with Google");
  await rect("lg_create", "Create a doctor account");
  await click("Create a doctor account");
  await shot("signup_account");
  await rect("su_google", "Continue with Google");
  await click("Continue with Google");
  await run(`const set = (id, v) => { const el = document.getElementById(id); const proto = el.tagName === "SELECT" ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, "value").set.call(el, v); el.dispatchEvent(new Event(el.tagName === "SELECT" ? "change" : "input", { bubbles: true })); };
    set("fn", "Dr. Kavya Menon"); set("ti", "MPT (Sports)"); set("sp", "Sports"); set("cl", "Stride Physio Clinic"); set("ci", "Pune");
    set("co", "State physiotherapy council"); set("rg", "MH-PT-11982"); set("yx", "6"); set("ph", "+91 98111 22334"); return true;`);
  await sleep(300);
  await shot("signup_details", 900);
  await rect("su_continue", "Continue");
  await click("Continue");
  await run(`document.getElementById("agree-registered").click(); document.getElementById("agree-data").click(); return true;`);
  await sleep(300);
  await shot("signup_confirm");
  await rect("su_create", "Create my account");
  await click("Create my account");
  await shot("signup_done");
  writeFileSync(`${OUT}/rects.json`, JSON.stringify({ width: W, height: H, rects }, null, 1));
  console.log("rects", Object.keys(rects).length);
} finally {
  try { ws?.close(); } catch { /* closing */ }
  chrome.kill();
}
