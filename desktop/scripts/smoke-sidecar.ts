/**
 * Headless Phase 0 verification of the sidecar lifecycle — no Electron, no display.
 *
 * Proves the hard unknown end to end:
 *   1. spawn the FastAPI sidecar (via uv in the backend dir),
 *   2. wait for /health,
 *   3. authenticate as the dev tenant and trigger the trivial agent loop,
 *   4. confirm it streamed output + captured a usage_event,
 *   5. tear the sidecar down cleanly.
 *
 * Run: `npm run smoke:sidecar` (from desktop/).
 */

import { tmpdir } from "node:os";
import { join } from "node:path";

import { resolveBackendConfig } from "../src/main/config.js";
import { SidecarManager } from "../src/main/sidecar.js";

async function main(): Promise<void> {
  const cfg = resolveBackendConfig();
  console.log(`[smoke] backend ${cfg.baseUrl} spawnSidecar=${cfg.spawnSidecar}`);

  // Isolated DB so the smoke run never collides with another backend instance.
  const dbPath = join(tmpdir(), `agentos-smoke-${Date.now()}.db`);
  const sidecar = new SidecarManager({
    host: cfg.host,
    port: cfg.port,
    baseUrl: cfg.baseUrl,
    env: {
      AGENTOS_OTEL_EXPORTER: "none",
      AGENTOS_LOG_LEVEL: "WARNING",
      AGENTOS_DATABASE_URL: `sqlite+aiosqlite:///${dbPath}`,
    },
  });
  sidecar.on("log", (m: string) => console.log(`[sidecar] ${m}`));

  const traceId = `desktop-smoke-${Date.now()}`;
  let exitCode = 0;
  try {
    console.log("[smoke] starting sidecar…");
    await sidecar.start();
    console.log(`[smoke] sidecar status=${sidecar.getStatus()}`);

    const headers = {
      Authorization: `Bearer ${cfg.apiKey}`,
      "Content-Type": "application/json",
      "X-Trace-Id": traceId,
    };

    const who = await (await fetch(`${cfg.baseUrl}/v1/whoami`, { headers })).json();
    console.log(`[smoke] authenticated tenant=${who.tenant_id}`);

    const run = await (
      await fetch(`${cfg.baseUrl}/v1/runs/sync`, {
        method: "POST",
        headers,
        body: JSON.stringify({ task: "hello from the desktop smoke test" }),
      })
    ).json();
    console.log(`[smoke] run ${run.run_id} status=${run.status} tokens=${run.total_tokens}`);
    console.log(`[smoke] output: ${run.output}`);

    const usage = await (
      await fetch(`${cfg.baseUrl}/v1/usage?run_id=${run.run_id}`, { headers })
    ).json();

    const ok =
      run.status === "completed" &&
      run.usage_event_id &&
      run.total_tokens > 0 &&
      usage.length === 1 &&
      usage[0].trace_id === traceId;

    if (ok) {
      console.log(`[smoke] PASS — usage_event ${usage[0].id} carries trace_id ${traceId}`);
    } else {
      console.error("[smoke] FAIL — unexpected run/usage result", { run, usage });
      exitCode = 1;
    }
  } catch (err) {
    console.error(`[smoke] ERROR: ${(err as Error).message}`);
    exitCode = 1;
  } finally {
    console.log("[smoke] stopping sidecar…");
    await sidecar.stop();
    console.log(`[smoke] sidecar status=${sidecar.getStatus()}`);
  }
  process.exit(exitCode);
}

void main();
