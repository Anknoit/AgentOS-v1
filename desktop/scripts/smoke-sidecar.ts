/**
 * Headless verification of the sidecar lifecycle — no Electron, no display.
 *
 * Proves the hard unknown end to end:
 *   1. spawn the FastAPI sidecar (via uv in the backend dir),
 *   2. wait for /health,
 *   3. authenticate as the dev tenant,
 *   4. Phase 0 — trigger the trivial agent loop and confirm streamed output + a usage_event,
 *   5. Phase 1 — create a Support Desk agent, run it, and confirm a complete action log plus
 *      one model_call and one tool_call usage event, all carrying the client trace id,
 *   6. tear the sidecar down cleanly.
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
    const getJson = async (path: string) =>
      (await fetch(`${cfg.baseUrl}${path}`, { headers })).json();
    const postJson = async (path: string, body: unknown) =>
      (
        await fetch(`${cfg.baseUrl}${path}`, {
          method: "POST",
          headers,
          body: JSON.stringify(body),
        })
      ).json();

    const who = await getJson("/v1/whoami");
    console.log(`[smoke] authenticated tenant=${who.tenant_id}`);

    // --- Phase 0: the anonymous agent-loop spike ---
    const spike = await postJson("/v1/runs/sync", {
      task: "hello from the desktop smoke test",
    });
    console.log(`[smoke] spike run ${spike.run_id} status=${spike.status} tokens=${spike.total_tokens}`);
    const spikeUsage = await getJson(`/v1/usage?run_id=${spike.run_id}`);
    const spikeOk =
      spike.status === "completed" &&
      spike.usage_event_id &&
      spike.total_tokens > 0 &&
      spikeUsage.length === 1 &&
      spikeUsage[0].trace_id === traceId;

    // --- Phase 1: a real Support Desk agent, run as a managed job ---
    const agent = await postJson("/v1/agents", {
      name: "Smoke Desk",
      template: "support_desk",
    });
    console.log(`[smoke] created agent ${agent.id} version=${agent.current_version_id}`);

    const run = await postJson(`/v1/agents/${agent.id}/runs`, {
      task: "I need a refund on my order",
    });
    console.log(
      `[smoke] agent run ${run.id} status=${run.status} tokens=${run.total_tokens} tools=${run.tool_calls}`,
    );
    console.log(`[smoke] output: ${run.output}`);

    const actions = await getJson(`/v1/runs/${run.id}/actions`);
    const actionTypes = actions.map((a: { type: string }) => a.type);
    const usage = await getJson(`/v1/usage?run_id=${run.id}`);
    const usageKinds = usage.map((u: { event_type: string }) => u.event_type).sort();

    const agentOk =
      run.status === "completed" &&
      run.tool_calls === 1 &&
      run.total_tokens > 0 &&
      String(run.output).toLowerCase().includes("refund") &&
      actionTypes[0] === "run_started" &&
      actionTypes[actionTypes.length - 1] === "run_completed" &&
      actionTypes.includes("tool_call") &&
      actionTypes.includes("model_call") &&
      usageKinds.length === 2 &&
      usageKinds[0] === "model_call" &&
      usageKinds[1] === "tool_call" &&
      usage.every((u: { trace_id: string }) => u.trace_id === traceId);

    if (spikeOk && agentOk) {
      console.log(
        `[smoke] PASS — Support Desk run ${run.id}: ${actions.length}-step audit log, ` +
          `usage [${usageKinds.join(", ")}] all tagged trace_id ${traceId}`,
      );
    } else {
      console.error("[smoke] FAIL — unexpected result", {
        spikeOk,
        agentOk,
        run,
        actionTypes,
        usageKinds,
      });
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
