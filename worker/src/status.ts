// worker/src/status.ts
import type { Env } from "./index";
import { LIMITS } from "./rate-limiter";

export async function handleStatus(userId: string, env: Env): Promise<Response> {
  const listed = await env.BUCKET.list({ prefix: `${userId}/` });
  const usedBytes = listed.objects.reduce((sum, obj) => sum + obj.size, 0);

  const now = new Date();
  const limits: Record<string, any> = {};

  const windows: { name: string; key: string }[] = [
    { name: "hourly", key: `rate:${userId}:hour:${now.toISOString().slice(0, 13)}` },
    { name: "daily", key: `rate:${userId}:day:${now.toISOString().slice(0, 10)}` },
    { name: "monthly", key: `rate:${userId}:month:${now.toISOString().slice(0, 7)}` },
  ];

  for (const w of windows) {
    const raw = await env.KV.get(w.key);
    const counters = raw ? JSON.parse(raw) : { req: 0, in: 0, out: 0 };
    const max = LIMITS[w.name as keyof typeof LIMITS];
    limits[w.name] = {
      requests: counters.req,
      max_requests: max.maxRequests,
      bytes_in: counters.in,
      bytes_out: counters.out,
    };
  }

  const userRaw = await env.KV.get(`user:${userId}`);
  const user = userRaw ? JSON.parse(userRaw) : {};

  return new Response(JSON.stringify({
    storage: { used_bytes: usedBytes, cap_bytes: 10 * 1024 * 1024 * 1024 },
    limits,
    tier: user.tier || "lite",
    billing: {
      status: user.status || "unknown",
      last_paid: user.last_paid || null,
    },
  }), {
    headers: { "Content-Type": "application/json" },
  });
}
