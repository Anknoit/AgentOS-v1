# AgentOS Desktop (Electron)

A thin Electron wrapper around the existing AgentOS web app. **No UI, component,
or CSS code is changed** — the desktop app runs the exact same build as the web
app, so the design is byte-for-byte identical.

## How it works

The AgentOS UI is a TanStack Start (SSR) app. Rather than re-render or convert
it, the Electron main process runs the app's own build and loads it in a window:

- **Dev** — loads the Vite dev server (`http://localhost:8123`), with HMR.
- **Production** — builds the app with the Nitro `node-server` preset, then the
  main process forks that self-contained server (`.output/server/index.mjs`) on
  a local port (default `34567`) and points the window at it.

A branded **splash screen** (`agentOs.png` + progress bar) shows immediately on
launch and is dismissed the moment the real UI is painted. The progress bar is
driven by actual boot milestones (server start → files loaded → UI ready), with
smooth easing in between.

Files:

- `electron/main.cjs` — window creation + dev/prod boot logic + splash handoff.
- `electron/preload.cjs` — secure `contextBridge` exposing a tiny read-only
  `window.agentosDesktop` marker (optional; the UI ignores it by default).
- `electron/splash.html` — the splash UI (image background + progress bar).
- `electron/splash-preload.cjs` — one-way IPC channel for progress updates.
- `electron/assets/agentOs.png` — splash artwork.
- `electron-builder.yml` — packaging config (ships `.output` as a resource).

## Scripts

```bash
# Run in development (Vite dev server + Electron window, hot reload)
npm run electron:dev

# Build the web app (node-server preset) and preview it in Electron, unpackaged
npm run electron:preview

# Build installable distributables into ./release (AppImage / dmg / nsis)
npm run electron:dist

# Build an unpacked app directory only (fast, no installer)
npm run electron:dist:dir
```

> On Linux CI/headless machines a display server (or `xvfb-run`) is needed to
> launch the GUI; packaging (`electron:dist`) does not need a display.

## Notes

- The production server is self-contained (its deps are bundled into `.output`),
  so the project `node_modules` are excluded from the packaged app to keep it
  small.
- `electron:build:web` sets `NITRO_PRESET=node-server` only for the desktop
  build; the normal `npm run build` (Cloudflare target used by Lovable) is
  untouched.
