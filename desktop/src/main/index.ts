/**
 * Electron main process.
 *
 * Responsibilities (Phase 0):
 *   - resolve the configurable backend URL (local sidecar vs remote),
 *   - in local mode, spawn + supervise the FastAPI sidecar and wait for /health,
 *   - create a BrowserWindow with a hardened renderer (contextIsolation on, nodeIntegration
 *     off, sandbox on) and a narrow preload bridge,
 *   - stub auto-update,
 *   - tear the sidecar down cleanly on quit.
 *
 * The UI itself (AgentOS_ui) is loaded as a thin client over the versioned backend API.
 */

import { app, BrowserWindow, ipcMain } from "electron";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { resolveBackendConfig } from "./config.js";
import { SidecarManager } from "./sidecar.js";
import { createUpdater } from "./updater.js";

const __dirname = dirname(fileURLToPath(import.meta.url));

const backend = resolveBackendConfig();
let sidecar: SidecarManager | null = null;
let mainWindow: BrowserWindow | null = null;

function log(msg: string): void {
  // eslint-disable-next-line no-console
  console.log(`[agentos-desktop] ${msg}`);
}

async function startBackend(): Promise<void> {
  if (!backend.spawnSidecar) {
    log(`using remote backend at ${backend.baseUrl} (no sidecar)`);
    return;
  }
  sidecar = new SidecarManager({
    host: backend.host,
    port: backend.port,
    baseUrl: backend.baseUrl,
  });
  sidecar.on("log", (m: string) => log(`[sidecar] ${m}`));
  sidecar.on("status", (s: string) => mainWindow?.webContents.send("sidecar:status", s));
  await sidecar.start();
  log(`sidecar ready at ${backend.baseUrl}`);
}

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 832,
    show: false,
    webPreferences: {
      preload: join(__dirname, "../preload/index.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  mainWindow.once("ready-to-show", () => mainWindow?.show());

  const startUrl = process.env.ELECTRON_START_URL;
  if (startUrl) {
    void mainWindow.loadURL(startUrl); // dev: Vite dev server from AgentOS_ui
  } else {
    // Packaged: load the built UI shipped alongside the shell.
    void mainWindow.loadFile(join(__dirname, "../../renderer/index.html")).catch(() => {
      void mainWindow?.loadURL(
        "data:text/html,<h1>AgentOS</h1><p>UI build not found. Set ELECTRON_START_URL for dev.</p>",
      );
    });
  }
}

// --- Secure IPC bridge: the renderer asks the main process for backend config/status only. ---
function registerIpc(): void {
  ipcMain.handle("backend:config", () => ({
    baseUrl: backend.baseUrl,
    apiKey: backend.apiKey,
  }));
  ipcMain.handle("sidecar:status", () => sidecar?.getStatus() ?? "idle");
}

app.whenReady().then(async () => {
  registerIpc();
  try {
    await startBackend();
  } catch (err) {
    log(`backend failed to start: ${(err as Error).message}`);
  }
  createWindow();

  const updater = createUpdater({ enabled: app.isPackaged, log });
  void updater.checkForUpdates();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", async (event) => {
  if (sidecar && sidecar.getStatus() !== "stopped") {
    event.preventDefault();
    log("stopping sidecar before quit…");
    await sidecar.stop();
    sidecar = null;
    app.quit();
  }
});
