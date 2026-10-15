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
 *   6. Phase 2 — store Slack + CRM credentials, run a connector-wired Support Desk agent, and
 *      confirm it reads/writes the CRM and posts to Slack (three metered connector calls),
 *   7. Phase 3 — confirm each billable step is rated into the ledger (spend per run/agent, wallet
 *      projection, active rate card) and that a hard budget stops an agent at its cap,
 *   8. Phase 4 — top up the wallet through the (mock) Razorpay gateway with a real HMAC-signed
 *      checkout confirmation, roll one itemized invoice across the fleet, reconcile the ledger,
 *      and watch a depleted prepaid balance stop a run,
 *   9. Phase 5 — confirm the durable event stream captured the fleet's usage and that replaying it
 *      through the idempotent pipeline is exactly-once (a re-replay changes nothing), plus the fair
 *      scheduler and model-router health are exposed,
 *  10. tear the sidecar down cleanly.
 *
 * Run: `npm run smoke:sidecar` (from desktop/).
 */

import { createHmac } from "node:crypto";
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

    // --- Phase 2: a connector-wired Support Desk agent using scoped, tenant-isolated creds ---
    await postJson("/v1/credentials", {
      connector_key: "crm",
      secret: "crm-smoke-key",
      provider_meta: { instance: "acme" },
    });
    await postJson("/v1/credentials", {
      connector_key: "slack",
      secret: "xoxb-smoke-token",
      provider_meta: { workspace: "acme" },
    });
    const connectors = await getJson("/v1/connectors");
    const connectorKeys = connectors.map((c: { key: string }) => c.key);

    const connAgent = await postJson("/v1/agents", {
      name: "Smoke Connected Desk",
      template: "support_desk_connected",
    });
    const connRun = await postJson(`/v1/agents/${connAgent.id}/runs`, {
      task: "I need a refund on my order",
    });
    const connActions = await getJson(`/v1/runs/${connRun.id}/actions`);
    const connectorCalls = connActions.filter(
      (a: { type: string }) => a.type === "connector_call",
    );
    const connectorTools = connectorCalls.map((a: { name: string }) => a.name).sort();
    const connUsage = await getJson(`/v1/usage?run_id=${connRun.id}`);
    const connectorUsage = connUsage.filter(
      (u: { event_type: string }) => u.event_type === "connector_call",
    );
    console.log(
      `[smoke] connected run ${connRun.id} status=${connRun.status} ` +
        `connectorCalls=[${connectorTools.join(", ")}]`,
    );

    const connectorOk =
      ["slack", "crm", "http", "mcp"].every((k) => connectorKeys.includes(k)) &&
      connRun.status === "completed" &&
      connectorTools.includes("crm.search_contacts") &&
      connectorTools.includes("crm.create_ticket") &&
      connectorTools.includes("slack.post_message") &&
      connectorCalls.every((a: { content: { outcome: string } }) => a.content.outcome === "ok") &&
      connectorUsage.length === 3 &&
      connUsage.every((u: { trace_id: string }) => u.trace_id === traceId);

    // --- Phase 3: metering, rating & budgets ---
    // Every billable step of the connected run was rated and posted to the ledger.
    const runSpend = await getJson(`/v1/spend?run_id=${connRun.id}`);
    const agentSpend = await getJson("/v1/spend/agents");
    const tenantSpend = await getJson("/v1/spend");
    const wallet = await getJson("/v1/wallet");
    const cards = await getJson("/v1/rate-cards");
    console.log(
      `[smoke] connected run spend ${runSpend.price_usd} over ${runSpend.event_count} events; ` +
        `wallet ${wallet.balance_usd}`,
    );

    // A hard budget stops an agent at its cap (online credit control).
    const cappedAgent = await postJson("/v1/agents", {
      name: "Smoke Capped Desk",
      template: "support_desk",
    });
    await postJson("/v1/budgets", {
      name: "smoke-cap",
      scope: "agent",
      scope_id: cappedAgent.id,
      period: "total",
      limit_usd: "0.0005",
      enforcement: "hard",
    });
    const cappedRun = await postJson(`/v1/agents/${cappedAgent.id}/runs`, {
      task: "I need a refund on my order",
    });
    const cappedAlerts = await getJson(`/v1/alerts?run_id=${cappedRun.id}`);
    console.log(
      `[smoke] capped run ${cappedRun.id} status=${cappedRun.status} ` +
        `alerts=[${cappedAlerts.map((a: { kind: string }) => a.kind).join(", ")}]`,
    );

    const meteringOk =
      runSpend.event_count >= 1 &&
      runSpend.price_nanos > 0 &&
      // BYO default card: price == cost (reconciles with provider numbers).
      runSpend.price_nanos === runSpend.cost_nanos &&
      // the wallet is the ledger's negative projection (no top-ups yet at this point)
      wallet.balance_nanos === -tenantSpend.price_nanos &&
      cards.some((c: { name: string; is_active: boolean }) => c.name === "default" && c.is_active) &&
      agentSpend.some(
        (a: { agent_id: string; price_nanos: number }) =>
          a.agent_id === connAgent.id && a.price_nanos > 0,
      ) &&
      // the hard cap stopped the agent (not failed) and logged it
      cappedRun.status === "stopped" &&
      cappedAlerts.some((a: { kind: string }) => a.kind === "budget_hard");

    // --- Phase 4: settlement & payments (Razorpay gateway, mock provider) ---
    // The mock gateway signs with the dev key secret, so the real HMAC verify path runs offline.
    const RZP_SECRET = "rzp-dev-secret-change-me";
    const balanceBeforeTopup = (await getJson("/v1/wallet")).balance_nanos;

    // 1. Create a $25 order and confirm it with a valid checkout signature.
    const topup = await postJson("/v1/billing/topups", { amount_usd: "25" });
    const paymentId = `pay_${String(topup.order_id).slice(6)}`;
    const signature = createHmac("sha256", RZP_SECRET)
      .update(`${topup.order_id}|${paymentId}`)
      .digest("hex");
    const confirmed = await postJson(`/v1/billing/topups/${topup.order_id}/confirm`, {
      razorpay_payment_id: paymentId,
      razorpay_signature: signature,
    });
    const walletAfterTopup = await getJson("/v1/wallet");
    console.log(
      `[smoke] topup ${topup.amount_usd} (order ${topup.order_id}) status=${confirmed.status}; ` +
        `wallet ${walletAfterTopup.balance_usd}`,
    );

    // 2. One itemized invoice across the whole fleet, rolled from the ledger.
    const invoice = await postJson("/v1/invoices", {});
    // 3. Reconcile: the wallet matches the ledger projection and the gateway charged what we credited.
    const recon = await getJson("/v1/billing/reconciliation");
    console.log(
      `[smoke] invoice ${invoice.number}: ${invoice.event_count} events ${invoice.price_usd}; ` +
        `recon drift balance=${recon.balance_drift_nanos} gateway=${recon.gateway_drift_nanos}`,
    );

    // 4. Refund the top-up (back to a slightly negative balance from prior usage), turn on prepaid
    //    enforcement, and watch the depleted balance stop a run (online credit control).
    await postJson(`/v1/billing/payments/${confirmed.id}/refund`, { amount_usd: "25" });
    await fetch(`${cfg.baseUrl}/v1/wallet`, {
      method: "PATCH",
      headers,
      body: JSON.stringify({ enforce_balance: true }),
    });
    const prepaidAgent = await postJson("/v1/agents", {
      name: "Smoke Prepaid Desk",
      template: "support_desk",
    });
    const prepaidRun = await postJson(`/v1/agents/${prepaidAgent.id}/runs`, {
      task: "I need a refund on my order",
    });
    const walletFinal = await getJson("/v1/wallet");
    console.log(
      `[smoke] prepaid run ${prepaidRun.id} status=${prepaidRun.status}; ` +
        `wallet ${walletFinal.balance_usd} reserved=${walletFinal.reserved_nanos}`,
    );

    const settlementOk =
      confirmed.status === "paid" &&
      confirmed.signature_verified === true &&
      // $25 credited (25e9 nanos), charged as 2500 gateway minor units (cents at fx 1)
      topup.amount_minor === 2500 &&
      walletAfterTopup.balance_nanos === balanceBeforeTopup + 25_000_000_000 &&
      invoice.number.startsWith("INV-") &&
      invoice.event_count >= 1 &&
      invoice.price_nanos > 0 &&
      invoice.cost_nanos === invoice.price_nanos && // BYO markup 0
      invoice.line_items.length >= 1 &&
      // the wallet is the ledger projection and the gateway reconciles
      recon.balance_drift_nanos === 0 &&
      recon.gateway_drift_nanos === 0 &&
      recon.within_tolerance === true &&
      // a depleted prepaid balance stopped the run (not failed), with no leaked reservation
      prepaidRun.status === "stopped" &&
      walletFinal.reserved_nanos === 0;

    // --- Phase 5: scale & reliability (durable stream + exactly-once replay, scheduler, router) ---
    const streamHealth = await getJson("/v1/ops/stream");
    // First replay re-feeds the whole stream through the idempotent pipeline; any captured-but-
    // unrated events (the Phase 0 spike path) are repaired exactly once (new entries == repaired).
    const replay1 = await postJson("/v1/ops/replay", {});
    // Second replay must be a perfect no-op — nothing new posted, balance unchanged (exactly-once).
    const replay2 = await postJson("/v1/ops/replay", { from_offset: 0 });
    const scheduler = await getJson("/v1/ops/scheduler");
    const providers = await getJson("/v1/ops/providers");
    console.log(
      `[smoke] stream head=${streamHealth.head_offset} events=${streamHealth.event_count}; ` +
        `replay#1 replayed=${replay1.replayed} repaired=${replay1.repaired} ` +
        `exactly_once=${replay1.exactly_once}; replay#2 new=${replay2.new_ledger_entries} ` +
        `Δbalance=${replay2.balance_delta_nanos}; scheduler max=${scheduler.max_concurrency}/` +
        `tenant=${scheduler.per_tenant_concurrency}; failover=${providers.failover_enabled}`,
    );

    const scaleOk =
      streamHealth.head_offset > 0 &&
      streamHealth.event_count > 0 &&
      // replay is exactly-once by construction (new ledger entries only ever repair gaps)…
      replay1.exactly_once === true &&
      replay1.replayed >= 1 &&
      // …and a re-replay over the now-healthy stream changes nothing at all
      replay2.new_ledger_entries === 0 &&
      replay2.balance_delta_nanos === 0 &&
      replay2.exactly_once === true &&
      scheduler.max_concurrency >= 1 &&
      scheduler.per_tenant_concurrency >= 1 &&
      typeof providers.failover_enabled === "boolean";

    if (spikeOk && agentOk && connectorOk && meteringOk && settlementOk && scaleOk) {
      console.log(
        `[smoke] PASS — Support Desk run ${run.id}: ${actions.length}-step audit log, ` +
          `usage [${usageKinds.join(", ")}] all tagged trace_id ${traceId}; ` +
          `connected run ${connRun.id}: 3 metered connector calls to Slack + CRM; ` +
          `rated spend ${runSpend.price_usd}, hard cap stopped run ${cappedRun.id}; ` +
          `topped up ${topup.amount_usd}, invoice ${invoice.number}, ` +
          `prepaid balance stopped run ${prepaidRun.id}; ` +
          `durable stream ${streamHealth.event_count} events, replay exactly-once`,
      );
    } else {
      console.error("[smoke] FAIL — unexpected result", {
        spikeOk,
        agentOk,
        connectorOk,
        meteringOk,
        settlementOk,
        scaleOk,
        run,
        actionTypes,
        usageKinds,
        connectorTools,
        cappedStatus: cappedRun.status,
        prepaidStatus: prepaidRun.status,
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
