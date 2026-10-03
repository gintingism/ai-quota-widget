const MAX_BODY_BYTES = 64 * 1024;
const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "Content-Type, X-Auth-Token",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Content-Type": "application/json",
};

function response(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: corsHeaders });
}

function validPayload(payload) {
  if (!payload || payload.version !== 1 || typeof payload.providers !== "object") return false;
  return Object.values(payload.providers).every((provider) =>
    provider && typeof provider === "object" &&
    (provider.quota_percent === null || typeof provider.quota_percent === "number") &&
    (provider.models === undefined || Array.isArray(provider.models))
  );
}

function authorized(request, env) {
  return Boolean(env.AUTH_TOKEN && request.headers.get("X-Auth-Token") === env.AUTH_TOKEN);
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: corsHeaders });
    const url = new URL(request.url);
    if (!url.pathname.startsWith("/api/quota/")) return response({ error: "Not found" }, 404);
    if (!authorized(request, env)) return response({ error: "Unauthorized" }, 401);
    if (url.pathname === "/api/quota/sync" && request.method === "POST") {
      if (Number(request.headers.get("Content-Length") || 0) > MAX_BODY_BYTES) {
        return response({ error: "Payload too large" }, 413);
      }
      let payload;
      try {
        const text = await request.text();
        if (text.length > MAX_BODY_BYTES) return response({ error: "Payload too large" }, 413);
        payload = JSON.parse(text);
      } catch {
        return response({ error: "Invalid JSON" }, 400);
      }
      if (!validPayload(payload)) return response({ error: "Invalid quota payload" }, 422);
      await env.QUOTA_KV.put("latest", JSON.stringify(payload));
      return response({ ok: true });
    }
    if (url.pathname === "/api/quota/latest" && request.method === "GET") {
      const latest = await env.QUOTA_KV.get("latest", "json");
      return latest ? response(latest) : response({ error: "No snapshot" }, 404);
    }
    return response({ error: "Not found" }, 404);
  },
};
