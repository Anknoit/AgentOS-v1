/**
 * Backend connection config.
 *
 * The client points at a **configurable backend URL** and never assumes which deployment it
 * talks to (local sidecar vs cloud). When `AGENTOS_BACKEND_URL` is set, the shell connects to
 * that remote backend and does NOT spawn a sidecar. Otherwise it spawns and supervises a local
 * FastAPI sidecar on `127.0.0.1:<port>`.
 */

export interface BackendConfig {
  /** Full base URL the renderer and IPC use, e.g. "http://127.0.0.1:8787". */
  baseUrl: string;
  /** True when this process owns a local sidecar it must spawn + supervise. */
  spawnSidecar: boolean;
  host: string;
  port: number;
  /** API key presented to the backend (dev default; replaced by real auth in Phase 6). */
  apiKey: string;
}

const DEFAULT_HOST = "127.0.0.1";
const DEFAULT_PORT = 8787;

export function resolveBackendConfig(env: NodeJS.ProcessEnv = process.env): BackendConfig {
  const explicit = env.AGENTOS_BACKEND_URL?.trim();
  const apiKey = env.AGENTOS_API_KEY?.trim() || "dev-local-key";

  if (explicit) {
    const url = new URL(explicit);
    return {
      baseUrl: explicit.replace(/\/$/, ""),
      spawnSidecar: false,
      host: url.hostname,
      port: Number(url.port) || (url.protocol === "https:" ? 443 : 80),
      apiKey,
    };
  }

  const host = env.AGENTOS_HOST?.trim() || DEFAULT_HOST;
  const port = Number(env.AGENTOS_PORT) || DEFAULT_PORT;
  return {
    baseUrl: `http://${host}:${port}`,
    spawnSidecar: true,
    host,
    port,
    apiKey,
  };
}
