// Browser smoke test using installed Chrome/Edge and Node 22+; no npm packages.
// Run from the project root: node tests/browser_smoke.mjs
import assert from "node:assert/strict";
import {spawn, spawnSync} from "node:child_process";
import {existsSync, mkdtempSync, readFileSync, writeFileSync, mkdirSync} from "node:fs";
import {tmpdir} from "node:os";
import {join, resolve} from "node:path";
import {createServer} from "node:net";
import {setTimeout as delay} from "node:timers/promises";

const root = resolve(".");
const temp = mkdtempSync(join(tmpdir(), "carewise-browser-"));
const browserProfile = join(temp, "browser");
const screenshots = join(temp, "screenshots");
mkdirSync(screenshots);
const binary = [process.env.CHROME_PATH,
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "/usr/bin/google-chrome", "/usr/bin/chromium",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
].filter(Boolean).find(existsSync);
assert(binary, "Chrome/Edge not found. Set CHROME_PATH to your browser executable.");
const probe = createServer();
await new Promise(resolve => probe.listen(0, "127.0.0.1", resolve));
const port = probe.address().port;
await new Promise(resolve => probe.close(resolve));
const base = "http://127.0.0.1:" + port;
let server, chrome, ws;
let serverLog = "";
const pending = new Map();
const errors = [];
let nextId = 0;

async function waitFor(check, label, timeout = 20000) {
  const end = Date.now() + timeout;
  let last;
  while (Date.now() < end) {
    try { if (await check()) return; } catch (error) { last = error; }
    await delay(100);
  }
  throw new Error("Timed out: " + label + (last ? " (" + last.message + ")" : ""));
}
function command(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++nextId;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(method + " timed out")); }, 30000);
    pending.set(id, {resolve, reject, timer});
    ws.send(JSON.stringify({id, method, params}));
  });
}
async function evaluate(expression) {
  const result = await command("Runtime.evaluate", {expression, returnByValue: true, awaitPromise: true});
  if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
  return result.result.value;
}
async function waitExpression(expression, label) { await waitFor(() => evaluate(expression), label); }
async function navigate(path) {
  await command("Page.navigate", {url: base + path});
  await waitExpression("document.readyState === 'complete' && location.pathname === " + JSON.stringify(path.split("?")[0]), "navigate " + path);
}
async function viewport(width, height) {
  await command("Emulation.setDeviceMetricsOverride", {width, height, deviceScaleFactor: 1, mobile: width < 600});
}
async function screenshot(name) {
  await delay(200);
  const {data} = await command("Page.captureScreenshot", {format: "png", captureBeyondViewport: false});
  writeFileSync(join(screenshots, name + ".png"), Buffer.from(data, "base64"));
}
async function fill(values) {
  await evaluate("(() => { const values = " + JSON.stringify(values) + "; for (const [selector, value] of Object.entries(values)) { const el = document.querySelector(selector); el.value = value; el.dispatchEvent(new Event('input', {bubbles: true})); } })()");
}
async function click(selector) { await evaluate("document.querySelector(" + JSON.stringify(selector) + ").click()"); }
try {
  // Synthetic credentials exist only in this test's temporary database.
  const seed = spawnSync(process.env.PYTHON || "python", ["-B", "-c",
    "from app.auth import init_db,database,hash_password; import time; init_db(); db=database(); conn=db.__enter__(); conn.execute(\"INSERT INTO users (name,email,password_hash,created_at,role) VALUES (?,?,?,?,?)\", ('Browser Admin','admin-browser@example.com',hash_password('admin-browser-passphrase'),int(time.time()),'admin')); db.__exit__(None,None,None)"
  ], {cwd:root, windowsHide:true, env:{...process.env,AUTH_DB_PATH:join(temp,"auth.sqlite3")}, encoding:"utf8"});
  assert.equal(seed.status, 0, seed.stderr);
  server = spawn(process.env.PYTHON || "python", ["-B", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(port), "--log-level", "warning"], {
    cwd: root, windowsHide: true, env: {...process.env, AUTH_DB_PATH: join(temp, "auth.sqlite3"), COOKIE_SECURE: "0"},
    stdio: ["ignore", "pipe", "pipe"],
  });
  server.stdout.on("data", data => { serverLog += data; });
  server.stderr.on("data", data => { serverLog += data; });
  await waitFor(async () => (await fetch(base + "/login")).ok, "FastAPI startup");
  chrome = spawn(binary, ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--remote-debugging-port=0", "--user-data-dir=" + browserProfile, "about:blank"], {windowsHide: true, stdio: "ignore"});
  const devtoolsFile = join(browserProfile, "DevToolsActivePort");
  await waitFor(() => existsSync(devtoolsFile), "browser startup");
  const debugPort = readFileSync(devtoolsFile, "utf8").split("\n")[0].trim();
  const target = await (await fetch("http://127.0.0.1:" + debugPort + "/json/new?about:blank", {method: "PUT"})).json();
  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { ws.addEventListener("open", resolve, {once: true}); ws.addEventListener("error", reject, {once: true}); });
  ws.addEventListener("message", event => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const waiter = pending.get(message.id); pending.delete(message.id); clearTimeout(waiter.timer);
      if (message.error) waiter.reject(new Error(JSON.stringify(message.error)));
      else waiter.resolve(message.result);
    } else if (message.method === "Runtime.exceptionThrown") errors.push(message.params.exceptionDetails.text);
  });
  await command("Page.enable");
  await command("Runtime.enable");
  await viewport(1440, 1000);
  await navigate("/login");
  await screenshot("login-desktop");
  assert.equal(await evaluate("document.querySelector('#auth-title').textContent"), "Welcome back.");
  await navigate("/register");
  await viewport(390, 844);
  assert(await evaluate("document.documentElement.scrollWidth <= innerWidth"), "Registration overflows on mobile");
  await screenshot("register-mobile");
  await fill({"#full-name": "Browser Test", "#email": "browser@example.com", "#password": "browser-passphrase-2026", "#confirm-password": "mismatch"});
  await evaluate("document.querySelector('#auth-form').requestSubmit()");
  assert.equal(await evaluate("document.querySelector('#confirm-password').checkValidity()"), false);
  await fill({"#confirm-password": "browser-passphrase-2026"});
  await evaluate("document.querySelector('#auth-form').requestSubmit()");
  await waitExpression("location.pathname === '/home' && document.querySelector('#user-name')?.textContent === 'Browser Test'", "registration redirect");
  await waitExpression("!document.querySelector('#first-assessment').hidden", "first-time home");
  assert.equal(await evaluate("document.querySelector('#saved-assessment').hidden"), true);
  await screenshot("home-first-time-mobile");
  await click("#start-assessment");
  await waitExpression("location.pathname === '/assessment' && document.querySelector('#next-button')?.disabled === false", "start assessment");
  assert(await evaluate("document.documentElement.scrollWidth <= innerWidth"), "Dashboard overflows on mobile");
  await screenshot("assessment-mobile");
  await viewport(1440, 1000);
  await screenshot("assessment-desktop");
  await fill({'[name="age"]': "10"});
  await click("#next-button");
  assert.equal(await evaluate("document.querySelector('.form-step:not([hidden])').dataset.step"), "0", "Invalid age should block progress");
  await fill({'[name="age"]': "45"});
  for (let i = 1; i <= 4; i++) {
    await click("#next-button");
    assert.equal(await evaluate("document.querySelector('.form-step:not([hidden])').dataset.step"), String(i));
  }
  await fill({'[name="horizon_years"]': "1"});
  await click("#go");
  await waitExpression("document.querySelectorAll('#out .plan').length > 0", "prediction results");
  assert.equal(await evaluate("location.pathname"), "/home");
  assert.equal(await evaluate("document.querySelector('#first-assessment').hidden"), true);
  assert.equal(await evaluate("document.querySelector('#retake-button').hidden"), false);
  await navigate("/home");
  await waitExpression("document.querySelectorAll('#out .plan').length > 0", "saved results after reload");
  await screenshot("results-desktop");
  await viewport(390, 844);
  assert(await evaluate("document.documentElement.scrollWidth <= innerWidth"), "Results overflow on mobile");
  await screenshot("results-mobile");
  await click("#logout-button");
  await waitExpression("location.pathname === '/login' && document.querySelector('#auth-form')", "logout redirect");
  await fill({"#email": "browser@example.com", "#password": "incorrect-password"});
  await evaluate("document.querySelector('#auth-form').requestSubmit()");
  await waitExpression("!document.querySelector('#auth-error').hidden", "invalid login error");
  assert.equal(await evaluate("document.querySelector('#auth-error').textContent"), "Email or password is incorrect.");
  await fill({"#password": "browser-passphrase-2026"});
  await evaluate("document.querySelector('#auth-form').requestSubmit()");
  await waitExpression("location.pathname === '/home' && document.querySelector('#user-name')?.textContent === 'Browser Test'", "login redirect");
  await waitExpression("document.querySelectorAll('#out .plan').length > 0", "saved results after login");
  await click("#retake-button");
  await waitExpression("location.pathname === '/assessment' && document.querySelector('#next-button')?.disabled === false", "retake assessment");
  await click(".home-link");
  await waitExpression("location.pathname === '/home' && document.querySelectorAll('#out .plan').length > 0", "cancel keeps saved assessment");
  await click("#logout-button");
  await waitExpression("location.pathname === '/login'", "final logout");
  await command("Page.navigate", {url: base + "/assessment"});
  await waitExpression("location.pathname === '/login' && document.querySelector('#auth-form')", "protected page redirect");

  await navigate("/admin/login");
  await fill({"#email":"admin-browser@example.com","#password":"admin-browser-passphrase"});
  await evaluate("document.querySelector('#auth-form').requestSubmit()");
  await waitExpression("location.pathname === '/admin' && document.querySelector('#add-plan')?.disabled === false", "admin sign in");
  await viewport(1440,1000);
  await screenshot("admin-desktop");
  await click("#plans-body button");
  await fill({"#field-base_premium_inr":"6200","#field-risk_condition":"diabetes","#field-min_risk_pct":"0","#field-max_risk_pct":"0"});
  await evaluate("document.querySelector('#plan-form').requestSubmit()");
  await waitExpression("!document.querySelector('#plan-dialog').open && document.querySelector('#plans-body').textContent.includes('6,200')", "plan edit");
  await click("#plans-body button");
  assert.equal(await evaluate("document.querySelector('#field-risk_condition').value"), "diabetes");
  assert.equal(await evaluate("document.querySelector('#field-max_risk_pct').value"), "0");
  await screenshot("plan-risk-editor");
  await click('[data-close="plan-dialog"]');
  await click("#add-plan");
  await fill({"#field-plan_id":"BROWSER_PLAN","#field-plan_name":"Browser Sample Plan","#field-description":"A sample plan created by the browser test."});
  await evaluate("document.querySelector('#plan-form').requestSubmit()");
  await waitExpression("document.querySelector('#plans-body').textContent.includes('Browser Sample Plan')", "plan creation");
  await click('[data-panel="rules-panel"]');
  await fill({"#field-smoker_premium_loading_pct":"15"});
  await evaluate("document.querySelector('#rules-form').requestSubmit()");
  await waitExpression("document.querySelector('#page-notice').textContent.includes('Pricing rules saved')", "save risk factors");
  await viewport(390,844);
  assert(await evaluate("document.documentElement.scrollWidth <= innerWidth"), "Admin layout overflows on mobile");
  await screenshot("admin-mobile");
  await click('[data-panel="users-panel"]');
  await click("#users-body button");
  await fill({"#admin-password":"admin-browser-passphrase","#reset-password":"browser-reset-passphrase","#reset-confirm":"browser-reset-passphrase"});
  await evaluate("document.querySelector('#reset-form').requestSubmit()");
  await waitExpression("!document.querySelector('#reset-dialog').open", "user password reset");
  await click(".account-profile-link");
  await waitExpression("document.querySelector('#profile-role')?.textContent === 'Administrator'", "admin profile");
  assert.equal(await evaluate("document.querySelectorAll('a[href=\"/profile\"]').length"), 1);
  assert(await evaluate("document.querySelector('#user-name').getBoundingClientRect().width > 0"), "Account name must be visible on mobile");
  await screenshot("profile-mobile");
  await fill({"#current-password":"admin-browser-passphrase","#new-password":"admin-new-browser-passphrase","#confirm-new-password":"admin-new-browser-passphrase"});
  await evaluate("document.querySelector('#password-form').requestSubmit()");
  await waitExpression("location.pathname === '/login' && document.querySelector('#auth-notice')?.textContent.includes('Password changed')", "admin password changed");
  await fill({"#email":"admin-browser@example.com","#password":"admin-new-browser-passphrase"});
  await evaluate("document.querySelector('#auth-form').requestSubmit()");
  await waitExpression("location.pathname === '/admin' && document.querySelector('#add-plan')?.disabled === false", "new admin password");
  await click("#logout-button");
  await waitExpression("location.pathname === '/login' && document.querySelector('#auth-form')", "admin sign out");
  await fill({"#email":"browser@example.com","#password":"browser-reset-passphrase"});
  await evaluate("document.querySelector('#auth-form').requestSubmit()");
  await waitExpression("location.pathname === '/home' && document.querySelector('#user-name')?.textContent === 'Browser Test'", "reset user password");
  await waitExpression("document.querySelector('#retake-button')?.hidden === false", "saved assessment ready");
  await click("#retake-button");
  await waitExpression("document.querySelector('#next-button')?.disabled === false", "retake after admin risk update");
  for (let i=0;i<4;i++) await click("#next-button");
  await click("#go");
  await waitExpression("location.pathname === '/home' && document.querySelectorAll('#out .plan').length > 0", "new risk-filtered results");
  const newResult = await evaluate("fetch('/api/assessments/latest').then(r=>r.json())");
  assert(!newResult.assessment.result.all_eligible_plans.some(plan=>plan.plan_id==='P01'));
  assert(newResult.assessment.result.excluded_plans.some(plan=>plan.plan_id==='P01' && plan.reasons.some(reason=>reason.includes('allowed risk range'))));
  await click(".account-profile-link");
  await waitExpression("document.querySelector('#profile-role')?.textContent === 'User'", "user profile");
  await fill({"#current-password":"browser-reset-passphrase","#new-password":"user-self-changed-passphrase","#confirm-new-password":"user-self-changed-passphrase"});
  await evaluate("document.querySelector('#password-form').requestSubmit()");
  await waitExpression("location.pathname === '/login' && document.querySelector('#auth-notice')?.textContent.includes('Password changed')", "user password changed");
  assert.deepEqual(errors, [], "Browser JavaScript errors");
  console.log("PASS: desktop/mobile layout, registration, validation, all questionnaire steps, real prediction results, logout, failed login, successful login, protected page, admin catalogue and risk rules, user resets, and profile password changes.");
  console.log("Screenshots: " + screenshots);
} catch (error) {
  console.error(error);
  if (serverLog) console.error(serverLog.slice(-6000));
  process.exitCode = 1;
} finally {
  if (ws?.readyState === WebSocket.OPEN) {
    try { await command("Browser.close"); } catch {}
    ws.close();
  }
  if (chrome && chrome.exitCode === null) chrome.kill();
  if (server && server.exitCode === null) {
    const ended = new Promise(resolve => server.once("exit", resolve));
    server.kill();
    await Promise.race([ended, delay(5000)]);
  }
}
