import assert from "node:assert/strict";
import test from "node:test";

import { createHandler } from "../src/worker.js";

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

test("reports a running workflow", async () => {
  const calls = [];
  const handler = createHandler({
    verify: authenticated,
    fetchImpl: async (url, options = {}) => {
      calls.push([url, options.method || "GET"]);
      return new Response(JSON.stringify({ state: "active" }), { status: 200 });
    }
  });
  const response = await handler(new Request("https://control.test/api/state", { headers: { Origin: env.APP_ORIGIN } }), env);
  assert.equal(response.status, 200);
  assert.equal((await response.json()).state, "running");
  assert.equal(calls.length, 1);
});

test("pause disables the scheduled workflow", async () => {
  const calls = [];
  const handler = createHandler({
    verify: authenticated,
    fetchImpl: async (url, options = {}) => {
      calls.push([url, options.method]);
      return new Response(null, { status: 204 });
    }
  });
  const response = await handler(new Request("https://control.test/api/control", {
    method: "POST",
    headers: { Origin: env.APP_ORIGIN, "Content-Type": "application/json" },
    body: JSON.stringify({ action: "pause" })
  }), env);
  assert.equal((await response.json()).state, "paused");
  assert.match(calls[0][0], /pickup-watch\.yml\/disable$/);
  assert.equal(calls[0][1], "PUT");
});

test("resume enables the workflow and starts an immediate scan", async () => {
  const calls = [];
  const handler = createHandler({
    verify: authenticated,
    fetchImpl: async (url, options = {}) => {
      calls.push([url, options.method]);
      return new Response(null, { status: 204 });
    }
  });
  const response = await handler(new Request("https://control.test/api/control", {
    method: "POST",
    headers: { Origin: env.APP_ORIGIN, "Content-Type": "application/json" },
    body: JSON.stringify({ action: "resume" })
  }), env);
  assert.equal((await response.json()).state, "running");
  assert.match(calls[0][0], /pickup-watch\.yml\/enable$/);
  assert.match(calls[1][0], /pickup-watch\.yml\/dispatches$/);
});

test("rejects a request without valid Access identity", async () => {
  const handler = createHandler({ verify: async () => { throw new Error("authentification Cloudflare Access requise"); } });
  const response = await handler(new Request("https://control.test/api/state", { headers: { Origin: env.APP_ORIGIN } }), env);
  assert.equal(response.status, 401);
  assert.equal((await response.json()).error, "unauthorized");
});

