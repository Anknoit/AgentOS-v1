// AgentOS Desktop — preload.
// Minimal, secure bridge. The web UI runs exactly as it does in the browser;
// we only expose a tiny, read-only marker so app code could detect desktop mode
// if it ever needs to. No UI behavior is changed by default.

const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("agentosDesktop", {
  isDesktop: true,
  platform: process.platform,
  version: process.versions.electron,
});
