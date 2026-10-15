# AgentOS desktop shell

The Electron client over the backend. Its Phase 0 job is the hard unknown: **spawn and
supervise the FastAPI sidecar**, connect the renderer to a **configurable backend URL** over a
**secure IPC bridge**, and stub auto-update.

## What it does

- `src/main/config.ts` — resolves the backend URL. `AGENTOS_BACKEND_URL` set ⇒ connect to a
  remote backend (no sidecar); unset ⇒ spawn a local sidecar on `127.0.0.1:8787`.
- `src/main/sidecar.ts` — `SidecarManager`: spawns the backend (`uv run agentos serve` in dev,
  the bundled PyInstaller binary when packaged), polls `/health`, restarts on crash with
  backoff, and terminates cleanly on quit (SIGTERM → SIGKILL). Imports **no** `electron`, so it
  is testable headlessly.
- `src/main/index.ts` — Electron main: hardened `BrowserWindow` (`contextIsolation: true`,
  `nodeIntegration: false`, `sandbox: true`), loads the UI, wires IPC + auto-update.
- `src/preload/index.ts` — narrow `window.agentos` bridge (backend config + sidecar status
  only; never raw `ipcRenderer`/Node).
- `src/main/updater.ts` — auto-update entrypoint (stub until a signed release feed exists).

## Verify (headless — no display needed)

```bash
npm install                 # ELECTRON_SKIP_BINARY_DOWNLOAD=1 is fine if you only verify
npm run typecheck
npm run smoke:sidecar       # spawns the real backend, runs the agent loop, checks usage, stops
```

`smoke:sidecar` is the Phase 0 exit criterion end to end (minus the GUI window): launch →
sidecar starts → authenticate → trigger the agent loop → streamed output → one trace spanning
client → API → worker. It uses an isolated temp SQLite DB, so it never collides with another
backend instance.

## Run the full app (needs a display + the Electron binary)

```bash
npm install                 # downloads the Electron binary
# dev: point at the UI's Vite dev server and let the shell boot the backend sidecar
ELECTRON_START_URL=http://localhost:8123 npm start
```

## Package

`electron-builder.yml` ships the compiled shell plus the backend as a PyInstaller binary
(`backend/dist/agentos-backend`, built separately) into `resources/backend/`, which
`SidecarManager` launches as the local sidecar.

> Note on self-hosted mode: the local sidecar is for dev and single-tenant. 24/7 agents do not
> run on a laptop — self-hosted means *their server*, not their desktop (see the development
> plan's cross-cutting decisions).
