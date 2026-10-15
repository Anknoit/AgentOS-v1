/**
 * Preload bridge (runs with contextIsolation on, no node integration in the renderer).
 *
 * Exposes a *narrow* typed surface on `window.agentos` — never the raw ipcRenderer or Node. The
 * renderer uses `baseUrl` to talk to the versioned backend API/WebSocket directly; the main
 * process only brokers config and sidecar status.
 */

import { contextBridge, ipcRenderer } from "electron";

export interface BackendConfigDTO {
  baseUrl: string;
  apiKey: string;
}

const api = {
  /** Resolve the backend base URL + dev API key the renderer should use. */
  getBackendConfig: (): Promise<BackendConfigDTO> => ipcRenderer.invoke("backend:config"),
  /** Current sidecar lifecycle status. */
  getSidecarStatus: (): Promise<string> => ipcRenderer.invoke("sidecar:status"),
  /** Subscribe to sidecar status changes. Returns an unsubscribe fn. */
  onSidecarStatus: (cb: (status: string) => void): (() => void) => {
    const listener = (_e: unknown, status: string) => cb(status);
    ipcRenderer.on("sidecar:status", listener);
    return () => ipcRenderer.removeListener("sidecar:status", listener);
  },
};

contextBridge.exposeInMainWorld("agentos", api);

export type AgentOSBridge = typeof api;
