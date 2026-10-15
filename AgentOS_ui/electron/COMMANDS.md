# AgentOS Desktop — Command Guide

Run all commands from the `AgentOS_ui/` folder.

## One-time setup

```bash
npm install          # install all dependencies (incl. Electron)
```

## Everyday use

```bash
npm run electron:dev       # ▶ open the desktop app with hot reload (use this while working)
npm run electron:preview   # ▶ open the app exactly as it ships (real production build)
```

- `electron:dev` → starts the Vite dev server + opens the window; edits reload live.
- `electron:preview` → builds the app, then opens that build in the window (no hot reload).

## Build installers (to share / distribute)

```bash
npm run electron:dist       # 📦 build installer(s) → ./release  (AppImage / .dmg / .exe)
npm run electron:dist:dir   # 📦 build an unpacked app folder only (faster, no installer)
```

Output lands in `AgentOS_ui/release/`.

## Web build only (no desktop window)

```bash
npm run electron:build:web  # builds the Node-server version into ./.output
```

## Handy to know

| Command | What it does |
|---|---|
| `npm run electron:dev` | Develop in the desktop window (live reload) |
| `npm run electron:preview` | See the final build in the desktop window |
| `npm run electron:dist` | Make shareable installers in `./release` |
| `npm run electron:dist:dir` | Make a runnable app folder in `./release` |

**Notes**
- On headless Linux (no screen), prefix with `xvfb-run`, e.g. `xvfb-run npm run electron:preview`.
- Dev app runs on port **8123**; the packaged app serves itself on port **34567** internally.
- Close the window (or `Ctrl+C` in the terminal) to stop.
