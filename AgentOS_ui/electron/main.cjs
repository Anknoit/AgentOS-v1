// AgentOS Desktop — Electron main process.
//
// This wrapper runs the EXISTING AgentOS web app unchanged so the UI/design is
// byte-for-byte identical to the browser build:
//   - dev:  loads the Vite dev server (ELECTRON_START_URL)
//   - prod: boots the app's own Nitro node-server build (.output/server/index.mjs)
//           on a local port and loads it in a BrowserWindow.
// No React/component/CSS code is modified by this layer.

const { app, BrowserWindow, shell, Menu } = require("electron");
const path = require("node:path");
const http = require("node:http");
const { once } = require("node:events");
const { fork } = require("node:child_process");

// Dev = running against the Vite dev server. Set AGENTOS_SERVE_BUILD=1 to run
// the production node-server build from source (unpackaged) for a local preview.
const isDev = !app.isPackaged && process.env.AGENTOS_SERVE_BUILD !== "1";
const DEV_URL = process.env.ELECTRON_START_URL || "http://localhost:3000";
const PROD_PORT = Number(process.env.AGENTOS_PORT || 34567);
const PROD_HOST = "127.0.0.1";

/** @type {import("node:child_process").ChildProcess | undefined} */
let serverProcess;
/** @type {BrowserWindow | undefined} */
let mainWindow;
/** @type {BrowserWindow | undefined} */
let splashWindow;

// Resolve the built Nitro server entry both when running from source
// (electron . ) and when packaged (app.asar.unpacked / resources).
function resolveServerEntry() {
  const candidates = [
    path.join(__dirname, "..", ".output", "server", "index.mjs"),
    path.join(process.resourcesPath || "", "app", ".output", "server", "index.mjs"),
    path.join(process.resourcesPath || "", ".output", "server", "index.mjs"),
  ];
  const fs = require("node:fs");
  for (const c of candidates) {
    try {
      if (fs.existsSync(c)) return c;
    } catch {
      /* ignore */
    }
  }
  return candidates[0];
}

function startProdServer() {
  const entry = resolveServerEntry();
  serverProcess = fork(entry, [], {
    env: {
      ...process.env,
      PORT: String(PROD_PORT),
      HOST: PROD_HOST,
      NITRO_PORT: String(PROD_PORT),
      NITRO_HOST: PROD_HOST,
      // In a packaged app process.execPath is the Electron binary; this makes
      // the forked child run as plain Node so it serves instead of opening a window.
      ELECTRON_RUN_AS_NODE: "1",
    },
    stdio: ["ignore", "inherit", "inherit", "ipc"],
  });
  serverProcess.on("exit", (code) => {
    if (code && code !== 0) console.error(`AgentOS server exited with code ${code}`);
  });
}

function waitForServer(url, { timeoutMs = 20000, intervalMs = 150 } = {}) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const req = http.get(url, (res) => {
        res.resume();
        resolve();
      });
      req.on("error", () => {
        if (Date.now() > deadline) reject(new Error(`Server not reachable at ${url}`));
        else setTimeout(attempt, intervalMs);
      });
    };
    attempt();
  });
}

function createWindow(targetUrl) {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 960,
    minHeight: 640,
    backgroundColor: "#f7f6f3",
    show: false,
    autoHideMenuBar: true,
    title: "AgentOS",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  // Note: showing the main window + dismissing the splash is handled in boot().

  // Open external links in the user's real browser, keep app navigation in-app.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("http://localhost") || url.startsWith(`http://${PROD_HOST}`)) {
      return { action: "allow" };
    }
    shell.openExternal(url);
    return { action: "deny" };
  });

  mainWindow.loadURL(targetUrl);

  if (isDev) mainWindow.webContents.openDevTools({ mode: "detach" });

  mainWindow.on("closed", () => {
    mainWindow = undefined;
  });
}

// Frameless splash shown immediately while the app boots. Displays agentOs.png
// with a progress bar fed by setProgress() milestones below.
function createSplash() {
  splashWindow = new BrowserWindow({
    width: 760,
    height: 434,
    resizable: false,
    frame: false,
    transparent: false,
    backgroundColor: "#ffffff",
    center: true,
    show: false,
    skipTaskbar: true,
    alwaysOnTop: true,
    title: "AgentOS",
    webPreferences: {
      preload: path.join(__dirname, "splash-preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  splashWindow.once("ready-to-show", () => splashWindow && splashWindow.show());
  splashWindow.loadFile(path.join(__dirname, "splash.html"));
  splashWindow.on("closed", () => {
    splashWindow = undefined;
  });
  return splashWindow;
}

// Push a progress update to the splash ({ value: 0-100, label }).
function setProgress(value, label) {
  if (splashWindow && !splashWindow.isDestroyed()) {
    splashWindow.webContents.send("splash:progress", { value, label });
  }
}

function dismissSplash() {
  if (splashWindow && !splashWindow.isDestroyed()) splashWindow.close();
}

const delay = (ms) => new Promise((r) => setTimeout(r, ms));

// Injected into the loaded page: resolves only once the UI has actually
// rendered — document complete, real content mounted (React hydrated), any
// charts have drawn their paths, and web fonts are ready — plus two paint
// frames so the handoff lands on a fully-drawn screen. Has its own ceiling so
// it can never hang the page. This reads the DOM only; it changes nothing.
const READINESS_SCRIPT = `new Promise((resolve) => {
  var start = Date.now();
  var MAX = 10000;
  function hasContent() {
    if (document.readyState !== 'complete') return false;
    if (!document.body || document.body.childElementCount === 0) return false;
    // something substantial has rendered (cards/sections/charts/tables)
    return !!document.querySelector(
      'main, [class*="section"], [class*="card"], .recharts-wrapper, table'
    );
  }
  function chartsReady() {
    var s = document.querySelectorAll('.recharts-surface, .recharts-wrapper');
    if (!s.length) return true; // no charts on this view
    for (var i = 0; i < s.length; i++) {
      if (s[i].querySelector('path, rect.recharts-rectangle, line')) return true;
    }
    return false;
  }
  function settle() {
    var fonts = (document.fonts && document.fonts.ready) ? document.fonts.ready : Promise.resolve();
    fonts.then(function () {
      requestAnimationFrame(function () {
        requestAnimationFrame(function () { resolve(true); });
      });
    });
  }
  function tick() {
    if ((hasContent() && chartsReady()) || (Date.now() - start) > MAX) settle();
    else setTimeout(tick, 120);
  }
  tick();
})`;

// Resolves when the app is fully rendered (or after a hard timeout).
function waitForAppReady(webContents, { timeoutMs = 12000 } = {}) {
  const loaded = webContents.isLoadingMainFrame()
    ? once(webContents, "did-finish-load").catch(() => {})
    : Promise.resolve();

  const ready = loaded.then(() =>
    webContents.executeJavaScript(READINESS_SCRIPT, true).catch(() => true),
  );

  return Promise.race([ready, delay(timeoutMs)]);
}

async function boot() {
  const splash = createSplash();
  // Wait for the splash DOM so early progress messages aren't lost (with a
  // timeout so a load hiccup can never block the whole app from starting).
  try {
    await Promise.race([
      once(splash.webContents, "did-finish-load"),
      new Promise((r) => setTimeout(r, 3000)),
    ]);
  } catch {
    /* ignore */
  }
  setProgress(8, "Starting AgentOS…");

  let url;
  if (isDev) {
    setProgress(30, "Connecting to dev server…");
    try {
      await waitForServer(DEV_URL);
    } catch {
      /* dev server may still be warming; load anyway */
    }
    url = DEV_URL;
  } else {
    setProgress(22, "Starting engine…");
    startProdServer();
    url = `http://${PROD_HOST}:${PROD_PORT}/`;
    setProgress(55, "Loading files & dependencies…");
    try {
      await waitForServer(url);
    } catch (err) {
      console.error(err);
    }
  }

  setProgress(78, "Preparing workspace…");
  createWindow(url);

  const wc = mainWindow.webContents;
  wc.once("did-finish-load", () => setProgress(90, "Rendering interface & charts…"));

  // Keep the splash up until the UI, data, and graphs have actually rendered —
  // not merely until the first frame is painted.
  await waitForAppReady(wc);

  setProgress(100, "Ready");
  await delay(300);
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.show();
  dismissSplash();
}

app.whenReady().then(() => {
  Menu.setApplicationMenu(null);
  boot();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) boot();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

function stopServer() {
  if (serverProcess && !serverProcess.killed) {
    serverProcess.kill();
    serverProcess = undefined;
  }
}

app.on("before-quit", stopServer);
app.on("will-quit", stopServer);
process.on("exit", stopServer);
