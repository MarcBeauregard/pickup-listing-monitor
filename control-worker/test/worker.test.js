import assert from "node:assert/strict";
import test from "node:test";

import { createHandler, createSerialCoordinator } from "../src/worker.js";

const env = {
  APP_ORIGIN: "https://example.github.io",
  GITHUB_OWNER: "owner",
  GITHUB_REPO: "pickup-listing-monitor",
  GITHUB_WORKFLOW_FILE: "pickup-watch.yml",
  GITHUB_REF: "main"
};

function authenticated() {
  return { email: "marc@example.test" };
}

function request(path, options = {}) {
  return new Request(`https://control.test${path}`, {
    ...options,
    headers: { Origin: env.APP_ORIGIN, ...(options.headers || {}) }
  });
}

function control(action) {
  return request("/api/control", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action })
  });
}

test("reports a running workflow", async () => {
  const calls = [];
  const handler = createHandler({
    verify: authenticated,
    coordinate: createSerialCoordinator(),
    fetchImpl: async (url, options = {}) => {
      calls.push([url, options.method || "GET"]);
      return new Response(JSON.stringify({ state: "active" }), { status: 200 });
    }
  });
  const response = await handler(request("/api/state"), env);
  assert.equal(response.status, 200);
  assert.equal((await response.json()).state, "running");
  assert.equal(calls.length, 1);
});

test("pause disables an active scheduled workflow", async () => {
  const calls = [];
  const handler = createHandler({
    verify: authenticated,
    coordinate: createSerialCoordinator(),
    fetchImpl: async (url, options = {}) => {
      calls.push([url, options.method || "GET"]);
      if ((options.method || "GET") === "GET") return Response.json({ state: "active" });
      return new Response(null, { status: 204 });
    }
  });
  const response = await handler(control("pause"), env);
  const result = await response.json();
  assert.equal(result.state, "paused");
  assert.equal(result.changed, true);
  assert.match(calls[1][0], /pickup-watch\.yml\/disable$/);
});

test("resume is idempotent and dispatches only on paused to running transition", async () => {
  const calls = [];
  let githubState = "disabled_manually";
  const handler = createHandler({
    verify: authenticated,
    coordinate: createSerialCoordinator(),
    fetchImpl: async (url, options = {}) => {
      const method = options.method || "GET";
      calls.push([url, method]);
      if (method === "GET") return Response.json({ state: githubState });
      if (url.endsWith("/enable")) githubState = "active";
      return new Response(null, { status: 204 });
    }
  });
  const first = await handler(control("resume"), env);
  const second = await handler(control("resume"), env);
  assert.equal((await first.json()).dispatch, "started");
  assert.equal((await second.json()).changed, false);
  assert.equal(calls.filter(([url]) => url.endsWith("/dispatches")).length, 1);
});

test("concurrent resume requests produce exactly one dispatch", async () => {
  const calls = [];
  let githubState = "disabled_manually";
  const handler = createHandler({
    verify: authenticated,
    coordinate: createSerialCoordinator(),
    fetchImpl: async (url, options = {}) => {
      const method = options.method || "GET";
      calls.push([url, method]);
      if (method === "GET") return Response.json({ state: githubState });
      if (url.endsWith("/enable")) {
        await new Promise((resolve) => setTimeout(resolve, 5));
        githubState = "active";
      }
      return new Response(null, { status: 204 });
    }
  });
  const responses = await Promise.all([handler(control("resume"), env), handler(control("resume"), env)]);
  const results = await Promise.all(responses.map((response) => response.json()));
  assert.deepEqual(results.map((result) => result.changed), [true, false]);
  assert.equal(calls.filter(([url]) => url.endsWith("/dispatches")).length, 1);
});

test("rapid concurrent pause and resume alternation stays inside dispatch cooldown", async () => {
  const calls = [];
  let githubState = "disabled_manually";
  const fixedNow = Date.parse("2026-08-05T12:00:00Z");
  const handler = createHandler({
    verify: authenticated,
    coordinate: createSerialCoordinator({ now: () => fixedNow }),
    fetchImpl: async (url, options = {}) => {
      const method = options.method || "GET";
      calls.push([url, method]);
      if (method === "GET") return Response.json({ state: githubState });
      if (url.endsWith("/enable")) githubState = "active";
      if (url.endsWith("/disable")) githubState = "disabled_manually";
      return new Response(null, { status: 204 });
    }
  });

  assert.equal((await (await handler(control("resume"), env)).json()).dispatch, "started");
  const responses = await Promise.all([
    handler(control("pause"), env),
    handler(control("resume"), env),
    handler(control("pause"), env),
    handler(control("resume"), env)
  ]);
  const results = await Promise.all(responses.map((response) => response.json()));
  const resumed = results.filter((result) => result.dispatch === "cooldown");
  assert.equal(calls.filter(([url]) => url.endsWith("/dispatches")).length, 1);
  assert.equal(resumed.length, 2);
  assert.equal(resumed[0].retry_after_seconds, 300);
  assert.equal(resumed[0].next_dispatch_at, "2026-08-05T12:05:00.000Z");
  assert.equal(responses[1].headers.get("Retry-After"), "300");
});

test("reconciles state when enable succeeds but dispatch fails", async () => {
  let githubState = "disabled_manually";
  const handler = createHandler({
    verify: authenticated,
    coordinate: createSerialCoordinator(),
    fetchImpl: async (url, options = {}) => {
      const method = options.method || "GET";
      if (method === "GET") return Response.json({ state: githubState });
      if (url.endsWith("/enable")) {
        githubState = "active";
        return new Response(null, { status: 204 });
      }
      return new Response("dispatch unavailable", { status: 503 });
    }
  });
  const response = await handler(control("resume"), env);
  const result = await response.json();
  assert.equal(response.status, 207);
  assert.deepEqual({ state: result.state, dispatch: result.dispatch }, { state: "running", dispatch: "failed" });
});

test("allows an unauthenticated preflight from the configured Pages origin", async () => {
  let verified = false;
  const handler = createHandler({ verify: async () => { verified = true; } });
  const response = await handler(request("/api/control", {
    method: "OPTIONS",
    headers: {
      "Access-Control-Request-Method": "POST",
      "Access-Control-Request-Headers": "content-type"
    }
  }), env);
  assert.equal(response.status, 204);
  assert.equal(response.headers.get("Access-Control-Allow-Origin"), env.APP_ORIGIN);
  assert.equal(verified, false);
});

test("rejects a hostile POST origin before authentication", async () => {
  let verified = false;
  const handler = createHandler({ verify: async () => { verified = true; } });
  const response = await handler(new Request("https://control.test/api/control", {
    method: "POST",
    headers: { Origin: "https://evil.example", "Content-Type": "application/json" },
    body: JSON.stringify({ action: "pause" })
  }), env);
  assert.equal(response.status, 403);
  assert.equal(response.headers.get("Access-Control-Allow-Origin"), null);
  assert.equal(verified, false);
});

test("rejects a request without valid Access identity", async () => {
  const handler = createHandler({ verify: async () => { throw new Error("authentification Cloudflare Access requise"); } });
  const response = await handler(request("/api/state"), env);
  assert.equal(response.status, 401);
  assert.equal((await response.json()).error, "unauthorized");
});
