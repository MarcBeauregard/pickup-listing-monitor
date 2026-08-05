function decodeBase64Url(value) {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
  return Uint8Array.from(atob(padded), (character) => character.charCodeAt(0));
}

function parseJwt(assertion) {
  const parts = assertion.split(".");
  if (parts.length !== 3) throw new Error("jeton Access invalide");
  const decoder = new TextDecoder();
  return {
    header: JSON.parse(decoder.decode(decodeBase64Url(parts[0]))),
    payload: JSON.parse(decoder.decode(decodeBase64Url(parts[1]))),
    signature: decodeBase64Url(parts[2]),
    signed: new TextEncoder().encode(`${parts[0]}.${parts[1]}`)
  };
}

export async function verifyAccess(request, env, fetchImpl = fetch) {
  const assertion = request.headers.get("Cf-Access-Jwt-Assertion");
  if (!assertion) throw new Error("authentification Cloudflare Access requise");
  const token = parseJwt(assertion);
  if (token.header.alg !== "RS256") throw new Error("algorithme Access invalide");
  const now = Math.floor(Date.now() / 1000);
  const audiences = Array.isArray(token.payload.aud) ? token.payload.aud : [token.payload.aud];
  const expectedIssuer = env.ACCESS_TEAM_DOMAIN.replace(/\/$/, "");
  if (token.payload.iss?.replace(/\/$/, "") !== expectedIssuer) throw new Error("émetteur Access invalide");
  if (!audiences.includes(env.ACCESS_AUD) || !Number.isFinite(token.payload.exp) || token.payload.exp <= now || (Number.isFinite(token.payload.nbf) && token.payload.nbf > now)) throw new Error("jeton Access expiré ou mauvais auditoire");

  const certsUrl = `${expectedIssuer}/cdn-cgi/access/certs`;
  const certsResponse = await fetchImpl(certsUrl);
  if (!certsResponse.ok) throw new Error("clés Access indisponibles");
  const { keys } = await certsResponse.json();
  const jwk = keys.find((key) => key.kid === token.header.kid);
  if (!jwk) throw new Error("clé Access inconnue");
  const key = await crypto.subtle.importKey(
    "jwk",
    jwk,
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false,
    ["verify"]
  );
  const valid = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, token.signature, token.signed);
  if (!valid) throw new Error("signature Access invalide");

  const email = String(token.payload.email || "").toLowerCase();
  const allowed = String(env.ALLOWED_EMAILS || "")
    .split(",")
    .map((value) => value.trim().toLowerCase())
    .filter(Boolean);
  if (!email || !allowed.includes(email)) throw new Error("utilisateur non autorisé");
  return { email };
}

function corsHeaders(request, env) {
  const origin = request.headers.get("Origin");
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Credentials": "true",
    "Access-Control-Allow-Headers": "Content-Type, Cf-Access-Jwt-Assertion",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Vary": "Origin"
  };
}

function json(request, env, value, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", ...corsHeaders(request, env) }
  });
}

async function githubRequest(env, path, options = {}, fetchImpl = fetch) {
  const response = await fetchImpl(`https://api.github.com/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}${path}`, {
    ...options,
    headers: {
      "Accept": "application/vnd.github+json",
      "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "pickup-watch-control",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers
    }
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`GitHub ${response.status}: ${detail.slice(0, 180)}`);
  }
  return response;
}

async function workflowState(env, fetchImpl) {
  const response = await githubRequest(env, `/actions/workflows/${env.GITHUB_WORKFLOW_FILE}`, {}, fetchImpl);
  const workflow = await response.json();
  return workflow.state === "active" ? "running" : "paused";
}

async function updateWorkflow(action, env, fetchImpl) {
  if (action !== "pause" && action !== "resume") throw new Error("action invalide");
  const file = env.GITHUB_WORKFLOW_FILE;
  const current = await workflowState(env, fetchImpl);
  if (action === "pause") {
    if (current === "paused") return { state: "paused", changed: false };
    await githubRequest(env, `/actions/workflows/${file}/disable`, { method: "PUT" }, fetchImpl);
    return { state: "paused", changed: true };
  }
  if (action === "resume") {
    if (current === "running") return { state: "running", changed: false, dispatch: "skipped" };
    await githubRequest(env, `/actions/workflows/${file}/enable`, { method: "PUT" }, fetchImpl);
    try {
      await githubRequest(
        env,
        `/actions/workflows/${file}/dispatches`,
        { method: "POST", body: JSON.stringify({ ref: env.GITHUB_REF || "main" }) },
        fetchImpl
      );
      return { state: "running", changed: true, dispatch: "started" };
    } catch (_error) {
      return { state: "running", changed: true, dispatch: "failed", partial: true };
    }
  }
}

export function createSerialCoordinator() {
  let tail = Promise.resolve();
  return (action, env, fetchImpl) => {
    const operation = tail.then(() => updateWorkflow(action, env, fetchImpl));
    tail = operation.catch(() => {});
    return operation;
  };
}

async function durableCoordinator(action, env) {
  if (!env.CONTROL_COORDINATOR) throw new Error("coordinateur de contrôle non configuré");
  const id = env.CONTROL_COORDINATOR.idFromName("pickup-watch-workflow");
  const response = await env.CONTROL_COORDINATOR.get(id).fetch("https://control.internal/", {
    method: "POST",
    body: JSON.stringify({ action })
  });
  if (!response.ok) throw new Error("coordinateur de contrôle indisponible");
  return response.json();
}

function originAllowed(request, env) {
  return request.headers.get("Origin") === env.APP_ORIGIN;
}

export function createHandler({ fetchImpl = fetch, verify = verifyAccess, coordinate = durableCoordinator } = {}) {
  return async function handle(request, env) {
    if (!originAllowed(request, env)) return new Response(JSON.stringify({ error: "forbidden_origin" }), { status: 403, headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" } });
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: { ...corsHeaders(request, env), "Cache-Control": "no-store" } });
    const url = new URL(request.url);
    if (!url.pathname.startsWith("/api/")) return json(request, env, { error: "not_found" }, 404);
    try {
      const identity = await verify(request, env, fetchImpl);
      if (request.method === "GET" && url.pathname === "/api/state") {
        return json(request, env, { state: await workflowState(env, fetchImpl), user: identity.email });
      }
      if (request.method === "POST" && url.pathname === "/api/control") {
        const body = await request.json();
        const result = await coordinate(body.action, env, fetchImpl);
        return json(request, env, { ...result, user: identity.email }, result.partial ? 207 : 200);
      }
      return json(request, env, { error: "not_found" }, 404);
    } catch (error) {
      const unauthorized = String(error.message).toLowerCase().includes("access") || String(error.message).includes("autorisé");
      return json(request, env, { error: unauthorized ? "unauthorized" : "gateway_error" }, unauthorized ? 401 : 502);
    }
  };
}

export class WorkflowCoordinator {
  constructor(_state, env) {
    this.env = env;
    this.tail = Promise.resolve();
  }

  fetch(request) {
    const operation = this.tail.then(async () => {
      const { action } = await request.json();
      return updateWorkflow(action, this.env, fetch);
    });
    this.tail = operation.catch(() => {});
    return operation.then((result) => new Response(JSON.stringify(result), {
      headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" }
    }));
  }
}

const handle = createHandler();

export default {
  fetch(request, env) {
    return handle(request, env);
  }
};
