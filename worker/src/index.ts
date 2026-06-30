export interface Env {
  BUCKET: R2Bucket;
  KV: KVNamespace;
  STRIPE_SECRET_KEY: string;
  STRIPE_WEBHOOK_SECRET: string;
  STRIPE_PRICE_QUARTERLY: string;
  STRIPE_PRICE_YEARLY: string;
  API_KEY_SALT: string;
  SITE_URL: string;
}

// Hard cap — stop accepting signups above this number
const MAX_USERS = 100;

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;

    // Kill switch — flip via: wrangler kv:key put --binding KV "service:paused" "true"
    const paused = await env.KV.get("service:paused");
    if (paused === "true") {
      // Let webhooks through so Stripe cancellations still process
      if (path !== "/v1/webhook/stripe") {
        return json({ error: "service_paused", message: "recall cloud is temporarily paused" }, 503);
      }
    }

    // CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
          "Access-Control-Allow-Headers": "Authorization, Content-Type",
        },
      });
    }

    // Stripe webhook — no auth required (verified by signature)
    if (path === "/v1/webhook/stripe" && request.method === "POST") {
      const { handleStripeWebhook } = await import("./stripe");
      return handleStripeWebhook(request, env);
    }

    // Checkout — no auth required (creates new subscription)
    if (path === "/v1/checkout" && request.method === "POST") {
      const { handleCheckout } = await import("./checkout");
      return handleCheckout(request, env, MAX_USERS);
    }

    // Retrieve API key after checkout — no auth (uses session ID)
    if (path === "/v1/checkout/key" && request.method === "GET") {
      const sessionId = url.searchParams.get("session_id");
      if (!sessionId) return json({ error: "missing_session_id" }, 400);
      const rawKey = await env.KV.get(`pending_key:${sessionId}`);
      if (!rawKey) return json({ error: "key_not_found_or_expired" }, 404);
      return json({ api_key: rawKey });
    }

    // All other routes require auth
    const { authenticate } = await import("./auth");
    const authResult = await authenticate(request, env);
    if (!authResult.ok) {
      return json({ error: authResult.error }, authResult.status);
    }
    const userId = authResult.userId;

    // Rate limit check
    const { checkRateLimit } = await import("./rate-limiter");
    const rateResult = await checkRateLimit(userId, request, env);
    if (!rateResult.ok) {
      return json({
        error: "rate_limited",
        window: rateResult.window,
        resets_in: rateResult.resetsIn,
      }, 429);
    }

    // Route to handlers
    const { handleFiles } = await import("./files");
    const { handleExport } = await import("./export");

    if (path.startsWith("/v1/files")) {
      return handleFiles(request, url, userId, env);
    }
    if (path === "/v1/status") {
      const { handleStatus } = await import("./status");
      return handleStatus(userId, env);
    }
    if (path === "/v1/export") {
      return handleExport(userId, env);
    }
    if (path === "/v1/auth/rotate" && request.method === "POST") {
      const { handleRotateKey } = await import("./auth");
      return handleRotateKey(userId, env);
    }

    return json({ error: "not_found" }, 404);
  },
};
