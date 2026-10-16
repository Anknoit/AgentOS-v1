import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AgentOSClient, ApiError } from "@/lib/agentos/client";
import { __setBackendConfigForTests } from "@/lib/agentos/config";
import { moneyNanos, nanosToUsd, usdToNanos } from "@/lib/agentos/format";

const BASE = "http://127.0.0.1:8787";

type FetchArgs = { url: string; init: RequestInit };
let lastCall: FetchArgs | undefined;

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    lastCall = { url: String(input), init: init ?? {} };
    const payload = body === undefined ? null : JSON.stringify(body);
    return Promise.resolve(new Response(payload, { status }));
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

beforeEach(() => {
  lastCall = undefined;
  __setBackendConfigForTests({ baseUrl: BASE, apiKey: "test-key-123" });
});

afterEach(() => {
  vi.unstubAllGlobals();
  __setBackendConfigForTests(undefined);
});

describe("AgentOSClient", () => {
  it("sends the API key as a bearer token and a trace id", async () => {
    mockFetch(200, []);
    await new AgentOSClient().listAgents();

    expect(lastCall?.url).toBe(`${BASE}/v1/agents`);
    const headers = lastCall?.init.headers as Record<string, string>;
    expect(headers["Authorization"]).toBe("Bearer test-key-123");
    expect(headers["X-Trace-Id"]).toMatch(/^[a-f0-9]+$/i);
  });

  it("serializes a JSON body with a content-type on writes", async () => {
    mockFetch(201, { order_id: "order_1", amount_usd: "$25.00" });
    await new AgentOSClient().createTopup({ amount_usd: 25 });

    expect(lastCall?.init.method).toBe("POST");
    const headers = lastCall?.init.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBe("application/json");
    expect(lastCall?.init.body).toBe(JSON.stringify({ amount_usd: 25 }));
  });

  it("encodes query params", async () => {
    mockFetch(200, []);
    await new AgentOSClient().listRuns({ agent_id: "a1", limit: 50 });
    expect(lastCall?.url).toBe(`${BASE}/v1/runs?agent_id=a1&limit=50`);
  });

  it("returns undefined for 204 responses", async () => {
    mockFetch(204, undefined);
    await expect(new AgentOSClient().deleteCredential("slack")).resolves.toBeUndefined();
  });

  it("maps a fraud hold (403 tenant_held) to an ApiError", async () => {
    mockFetch(403, { detail: { code: "tenant_held", message: "Tenant is on hold." } });
    const err = await new AgentOSClient().triggerRun("a1", "hi").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).isHeld).toBe(true);
    expect((err as ApiError).message).toBe("Tenant is on hold.");
  });

  it("maps a velocity breach (429) to a rate-limit ApiError", async () => {
    mockFetch(429, { detail: { code: "velocity_exceeded", message: "Too many runs." } });
    const err = await new AgentOSClient().triggerRun("a1", "hi").catch((e: unknown) => e);
    expect((err as ApiError).isRateLimited).toBe(true);
  });

  it("surfaces a network failure as a network_error ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new Error("ECONNREFUSED"))),
    );
    const err = await new AgentOSClient().whoami().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).code).toBe("network_error");
  });
});

describe("money helpers", () => {
  it("converts nanodollars to USD and back", () => {
    expect(nanosToUsd(1_500_000_000)).toBe(1.5);
    expect(usdToNanos(1.5)).toBe(1_500_000_000);
  });
  it("formats nanodollars as currency", () => {
    expect(moneyNanos(18_720_000_000)).toBe("$18.72");
    expect(moneyNanos(2_400_000, 4)).toBe("$0.0024");
  });
});
