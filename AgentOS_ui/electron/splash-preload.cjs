// Preload for the splash window: exposes a one-way channel for the main process
// to push progress updates ({ value, label }) into the splash UI.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("splashAPI", {
  onProgress: (cb) => {
    ipcRenderer.on("splash:progress", (_event, payload) => cb(payload));
  },
});
