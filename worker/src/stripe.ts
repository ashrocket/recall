import type { Env } from "./index";
import { hashApiKey } from "./auth";

async function verifyStripeSignature(body: string, sig: string, secret: string): Promise<boolean> {
  // Parse Stripe signature header: t=timestamp,v1=signature
  const parts: Record<string, string> = {};
  for (const item of sig.split(",")) {
    const [key, val] = item.split("=", 2);
    parts[key] = val;
  }

  if (!parts.t || !parts.v1) return false;

  // Stripe signs: timestamp.body
  const payload = `${parts.t}.${body}`;
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sigBytes = await crypto.subtle.sign("HMAC", key, encoder.encode(payload));
  const expected = Array.from(new Uint8Array(sigBytes))
    .map(b => b.toString(16).padStart(2, "0"))
    .join("");

  // Timing-safe comparison
  if (expected.length !== parts.v1.length) return false;
  let diff = 0;
  for (let i = 0; i < expected.length; i++) {
    diff |= expected.charCodeAt(i) ^ parts.v1.charCodeAt(i);
  }

  // Reject if timestamp is older than 5 minutes
  const age = Math.floor(Date.now() / 1000) - parseInt(parts.t, 10);
  if (age > 300 || age < -60) return false;

  return diff === 0;
}

export async function handleStripeWebhook(request: Request, env: Env): Promise<Response> {
  const body = await request.text();
  const sig = request.headers.get("stripe-signature");

  if (!sig) {
    return jsonResponse({ error: "missing_signature" }, 400);
  }

  // Verify webhook signature
  const valid = await verifyStripeSignature(body, sig, env.STRIPE_WEBHOOK_SECRET);
  if (!valid) {
    return jsonResponse({ error: "invalid_signature" }, 401);
  }

  let event: any;
  try {
    event = JSON.parse(body);
  } catch {
    return jsonResponse({ error: "invalid_json" }, 400);
  }

  switch (event.type) {
    case "checkout.session.completed":
      return handleCheckoutCompleted(event.data.object, env);
    case "invoice.paid":
      return handleInvoicePaid(event.data.object, env);
    case "invoice.upcoming":
      return handleInvoiceUpcoming(event.data.object, env);
    case "customer.subscription.deleted":
      return handleSubscriptionDeleted(event.data.object, env);
    default:
      return jsonResponse({ ok: true, ignored: event.type });
  }
}

async function handleCheckoutCompleted(session: any, env: Env): Promise<Response> {
  const customerId = session.customer;
  const email = session.customer_email || session.customer_details?.email;

  const rawBytes = new Uint8Array(32);
  crypto.getRandomValues(rawBytes);
  const rawKey = "sk_recall_" + Array.from(rawBytes).map(b => b.toString(16).padStart(2, "0")).join("");
  const keyHash = await hashApiKey(rawKey, env.API_KEY_SALT);

  const userId = `user_${customerId}`;

  await env.KV.put(`key:${keyHash}`, JSON.stringify({
    user_id: userId,
    email,
    tier: "lite",
    status: "active",
    stripe_customer_id: customerId,
    created: new Date().toISOString(),
  }));

  await env.KV.put(`user:${userId}`, JSON.stringify({
    stripe_customer_id: customerId,
    email,
    status: "active",
    api_key_hash: keyHash,
    created: new Date().toISOString(),
  }));

  await env.KV.put(`pending_key:${session.id}`, rawKey, { expirationTtl: 600 });

  // Increment global user count
  const countRaw = await env.KV.get("service:user_count");
  const count = countRaw ? parseInt(countRaw, 10) : 0;
  await env.KV.put("service:user_count", String(count + 1));

  return jsonResponse({ ok: true, user_id: userId });
}

async function handleInvoicePaid(invoice: any, env: Env): Promise<Response> {
  const customerId = invoice.customer;
  const userId = `user_${customerId}`;
  const userRaw = await env.KV.get(`user:${userId}`);

  if (userRaw) {
    const user = JSON.parse(userRaw);
    user.status = "active";
    user.last_paid = new Date().toISOString();
    await env.KV.put(`user:${userId}`, JSON.stringify(user));

    if (user.api_key_hash) {
      const keyRaw = await env.KV.get(`key:${user.api_key_hash}`);
      if (keyRaw) {
        const keyData = JSON.parse(keyRaw);
        keyData.status = "active";
        await env.KV.put(`key:${user.api_key_hash}`, JSON.stringify(keyData));
      }
    }
  }

  return jsonResponse({ ok: true });
}

async function handleInvoiceUpcoming(invoice: any, env: Env): Promise<Response> {
  const customerId = invoice.customer;
  const userId = `user_${customerId}`;

  const now = new Date();

  const monthKey = `rate:${userId}:month:${now.toISOString().slice(0, 7)}`;
  const lastMonthKey = `rate:${userId}:month:${new Date(now.getFullYear(), now.getMonth() - 1, 1).toISOString().slice(0, 7)}`;

  const current = await env.KV.get(monthKey);
  const previous = await env.KV.get(lastMonthKey);

  const hasActivity = (current && JSON.parse(current).req > 0) ||
                      (previous && JSON.parse(previous).req > 0);

  if (!hasActivity) {
    const userRaw = await env.KV.get(`user:${userId}`);
    if (userRaw) {
      const user = JSON.parse(userRaw);
      user.status = "inactive";
      user.inactive_since = now.toISOString();
      await env.KV.put(`user:${userId}`, JSON.stringify(user));
    }
  }

  return jsonResponse({ ok: true, active: hasActivity });
}

async function handleSubscriptionDeleted(subscription: any, env: Env): Promise<Response> {
  const customerId = subscription.customer;
  const userId = `user_${customerId}`;

  const userRaw = await env.KV.get(`user:${userId}`);
  if (userRaw) {
    const user = JSON.parse(userRaw);
    user.status = "inactive";
    user.cancelled_at = new Date().toISOString();
    await env.KV.put(`user:${userId}`, JSON.stringify(user));

    if (user.api_key_hash) {
      const keyRaw = await env.KV.get(`key:${user.api_key_hash}`);
      if (keyRaw) {
        const keyData = JSON.parse(keyRaw);
        keyData.status = "inactive";
        await env.KV.put(`key:${user.api_key_hash}`, JSON.stringify(keyData));
      }
    }

    // Decrement global user count
    const countRaw = await env.KV.get("service:user_count");
    const count = countRaw ? parseInt(countRaw, 10) : 0;
    if (count > 0) {
      await env.KV.put("service:user_count", String(count - 1));
    }
  }

  return jsonResponse({ ok: true });
}

function jsonResponse(data: any, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
