import type { Env } from "./index";

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*",
    },
  });
}

export async function handleCheckout(request: Request, env: Env, maxUsers: number): Promise<Response> {
  // Customer count cap — hard stop on new signups
  const countRaw = await env.KV.get("service:user_count");
  const count = countRaw ? parseInt(countRaw, 10) : 0;
  if (count >= maxUsers) {
    return json({
      error: "capacity_reached",
      message: "recall cloud is at capacity. Try self-hosting or check back later.",
    }, 503);
  }

  // Parse plan + optional email from request body
  let email: string | undefined;
  let plan = "quarterly";
  try {
    const body = await request.json() as { email?: string; plan?: string };
    email = body.email;
    if (body.plan === "yearly") plan = "yearly";
  } catch {
    // No body is fine — defaults to quarterly
  }

  const priceId = plan === "yearly" ? env.STRIPE_PRICE_YEARLY : env.STRIPE_PRICE_QUARTERLY;

  // Create Stripe checkout session via REST API (no SDK needed in Workers)
  const siteUrl = env.SITE_URL || new URL(request.url).origin;
  const params = new URLSearchParams({
    mode: "subscription",
    "payment_method_types[0]": "card",
    "line_items[0][price]": priceId,
    "line_items[0][quantity]": "1",
    success_url: `${siteUrl}/cloud.html?checkout=success&session_id={CHECKOUT_SESSION_ID}`,
    cancel_url: `${siteUrl}/cloud.html?checkout=cancelled`,
  });

  if (email) {
    params.set("customer_email", email);
  }

  const stripeRes = await fetch("https://api.stripe.com/v1/checkout/sessions", {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${env.STRIPE_SECRET_KEY}`,
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: params.toString(),
  });

  if (!stripeRes.ok) {
    const err = await stripeRes.text();
    return json({ error: "stripe_error", detail: err }, 502);
  }

  const session = await stripeRes.json() as { id: string; url: string };
  return json({ session_id: session.id, url: session.url });
}
