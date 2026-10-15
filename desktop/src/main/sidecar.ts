/**
 * FastAPI sidecar lifecycle.
 *
 * In local mode the Electron shell spawns and supervises the backend as a child process:
 *   - spawn `agentos serve` (dev: via uv in the backend dir; packaged: the PyInstaller binary),
 *   - poll `/health` until it answers,
 *   - restart it with backoff if it crashes while we want it running,
 *   - terminate it cleanly on app quit (SIGTERM, then SIGKILL).
 *
 * This module deliberately imports nothing from `electron`, so it can be exercised headlessly
 * (see scripts/smoke-sidecar.ts) — spawning the sidecar is the Phase 0 hard unknown.
 */

import { ChildProcess, spawn } from "node:child_process";
import { EventEmitter } from "node:events";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export type SidecarStatus = "idle" | "starting" | "ready" | "restarting" | "stopped" | "failed";

export interface SidecarOptions {
  host: string;
  port: number;
  baseUrl: string;
  /** Override the launch command. Defaults to dev (uv) or packaged (bundled binary). */
  command?: { cmd: string; args: string[]; cwd?: string };
  env?: NodeJS.ProcessEnv;
  healthTimeoutMs?: number;
  healthIntervalMs?: number;
  maxRestarts?: number;
}

const __dirname = dirname(fileURLToPath(import.meta.url));

/** Locate the backend dir in a dev checkout (…/desktop/dist/main -> repo/backend). */
function findBackendDir(): string | null {
  let dir = __dirname;
  for (let i = 0; i < 6; i++) {
    const candidate = resolve(dir, "backend");
    if (existsSync(resolve(candidate, "pyproject.toml"))) return candidate;
    dir = resolve(dir, "..");
  }
  return null;
}

/** Path to the packaged PyInstaller sidecar binary (set by electron-builder extraResources). */
function packagedBinary(): string | null {
  const resourcesPath = (process as NodeJS.Process & { resourcesPath?: string }).resourcesPath;
  if (!resourcesPath) return null;
  const name = process.platform === "win32" ? "agentos-backend.exe" : "agentos-backend";
  const bin = resolve(resourcesPath, "backend", name);
  return existsSync(bin) ? bin : null;
}

function defaultCommand(port: number): { cmd: string; args: string[]; cwd?: string } {
  const bin = packagedBinary();
  if (bin) return { cmd: bin, args: ["serve", "--port", String(port)] };

  const backendDir = findBackendDir();
  if (backendDir) {
    return { cmd: "uv", args: ["run", "agentos", "serve", "--port", String(port)], cwd: backendDir };
  }
  // Last resort: assume `agentos` is on PATH.
  return { cmd: "agentos", args: ["serve", "--port", String(port)] };
}

export class SidecarManager extends EventEmitter {
  private proc: ChildProcess | null = null;
  private status: SidecarStatus = "idle";
  private wantRunning = false;
  private restarts = 0;
  private readonly opts: Required<Omit<SidecarOptions, "command" | "env">> &
    Pick<SidecarOptions, "command" | "env">;

  constructor(options: SidecarOptions) {
    super();
    this.opts = {
      healthTimeoutMs: 20_000,
      healthIntervalMs: 300,
      maxRestarts: 3,
      ...options,
    };
  }

  getStatus(): SidecarStatus {
    return this.status;
  }

  private setStatus(status: SidecarStatus): void {
    this.status = status;
    this.emit("status", status);
  }

  /** Spawn (if needed) and resolve once /health answers. */
  async start(): Promise<void> {
    this.wantRunning = true;

    // If a backend is already up at baseUrl (e.g. external/remote), just use it.
    if (await this.isHealthy()) {
      this.setStatus("ready");
      this.emit("ready", this.opts.baseUrl);
      return;
    }

    this.spawnProcess();
    await this.waitForHealth();
  }

  private spawnProcess(): void {
    const command = this.opts.command ?? defaultCommand(this.opts.port);
    this.setStatus(this.restarts > 0 ? "restarting" : "starting");
    this.emit("log", `spawning sidecar: ${command.cmd} ${command.args.join(" ")}`);

    const child = spawn(command.cmd, command.args, {
      cwd: command.cwd,
      env: {
        ...process.env,
        ...this.opts.env,
        AGENTOS_HOST: this.opts.host,
        AGENTOS_PORT: String(this.opts.port),
      },
      stdio: ["ignore", "pipe", "pipe"],
    });

    child.stdout?.on("data", (d) => this.emit("log", String(d).trimEnd()));
    child.stderr?.on("data", (d) => this.emit("log", String(d).trimEnd()));

    child.on("exit", (code, signal) => {
      this.proc = null;
      this.emit("log", `sidecar exited code=${code} signal=${signal}`);
      if (!this.wantRunning) {
        this.setStatus("stopped");
        return;
      }
      // Unexpected exit while we wanted it running -> restart with backoff.
      if (this.restarts < this.opts.maxRestarts) {
        this.restarts += 1;
        const backoff = Math.min(500 * 2 ** (this.restarts - 1), 5_000);
        this.emit("log", `restarting sidecar in ${backoff}ms (attempt ${this.restarts})`);
        setTimeout(() => {
          if (this.wantRunning) {
            this.spawnProcess();
            void this.waitForHealth().catch((e) => this.emit("log", `restart failed: ${e}`));
          }
        }, backoff);
      } else {
        this.setStatus("failed");
        this.emit("error", new Error("sidecar exceeded max restarts"));
      }
    });

    this.proc = child;
  }

  private async isHealthy(): Promise<boolean> {
    try {
      const res = await fetch(`${this.opts.baseUrl}/health`, {
        signal: AbortSignal.timeout(1_000),
      });
      if (!res.ok) return false;
      const body = (await res.json()) as { status?: string };
      return body.status === "ok";
    } catch {
      return false;
    }
  }

  private async waitForHealth(): Promise<void> {
    const deadline = Date.now() + this.opts.healthTimeoutMs;
    while (Date.now() < deadline) {
      if (await this.isHealthy()) {
        this.restarts = 0;
        this.setStatus("ready");
        this.emit("ready", this.opts.baseUrl);
        return;
      }
      await new Promise((r) => setTimeout(r, this.opts.healthIntervalMs));
    }
    this.setStatus("failed");
    throw new Error(`sidecar did not become healthy within ${this.opts.healthTimeoutMs}ms`);
  }

  /** Stop supervising and terminate the child (SIGTERM, then SIGKILL after a grace period). */
  async stop(graceMs = 5_000): Promise<void> {
    this.wantRunning = false;
    const child = this.proc;
    if (!child || child.exitCode !== null) {
      this.setStatus("stopped");
      return;
    }
    await new Promise<void>((resolveStop) => {
      const killTimer = setTimeout(() => {
        child.kill("SIGKILL");
      }, graceMs);
      child.once("exit", () => {
        clearTimeout(killTimer);
        resolveStop();
      });
      child.kill("SIGTERM");
    });
    this.setStatus("stopped");
  }
}
