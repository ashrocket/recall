import type { Env } from "./index";

interface RateOk { ok: true }
interface RateBlocked { ok: false; window: string; resetsIn: string }
type RateResult = RateOk | RateBlocked;

export const LIMITS = {
  hourly:  { maxRequests: 30,  maxBytesIn: 10_000_000,  maxBytesOut: 30_000_000,  ttl: 3600 },
  daily:   { maxRequests: 200, maxBytesIn: 50_000_000,  maxBytesOut: 100_000_000, ttl: 86400 },
  weekly:  { maxRequests: 800, maxBytesIn: 200_000_000, maxBytesOut: 500_000_000, ttl: 604800 },
  monthly: { maxRequests: 2000, maxBytesIn: 500_000_000, maxBytesOut: 1_000_000_000, ttl: 2678400 },
} as const;

type WindowName = keyof typeof LIMITS;

function windowKey(userId: string, window: WindowName): string {
  const now = new Date();
  switch (window) {
    case "hourly":  return `rate:${userId}:hour:${now.toISOString().slice(0, 13)}`;
    case "daily":   return `rate:${userId}:day:${now.toISOString().slice(0, 10)}`;
    case "weekly": {
      const jan1 = new Date(now.getFullYear(), 0, 1);
      const week = Math.ceil(((now.getTime() - jan1.getTime()) / 86400000 + jan1.getDay() + 1) / 7);
      return `rate:${userId}:week:${now.getFullYear()}-W${String(week).padStart(2, "0")}`;
    }
    case "monthly": return `rate:${userId}:month:${now.toISOString().slice(0, 7)}`;
  }
}

function timeUntilReset(window: WindowName): string {
  const now = new Date();
  let reset: Date;
  switch (window) {
    case "hourly":
      reset = new Date(now);
      reset.setMinutes(60, 0, 0);
      break;
    case "daily":
      reset = new Date(now);
      reset.setDate(reset.getDate() + 1);
      reset.setHours(0, 0, 0, 0);
      break;
    case "weekly":
      reset = new Date(now);
      reset.setDate(reset.getDate() + (7 - reset.getDay()));
      reset.setHours(0, 0, 0, 0);
      break;
    case "monthly":
      reset = new Date(now.getFullYear(), now.getMonth() + 1, 1);
      break;
  }
  const diffMs = reset.getTime() - now.getTime();
  const hours = Math.floor(diffMs / 3600000);
  const minutes = Math.floor((diffMs % 3600000) / 60000);
  if (hours > 24) return `${Math.floor(hours / 24)}d ${hours % 24}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

export async function checkRateLimit(userId: string, request: Request, env: Env): Promise<RateResult> {
  for (const [window, limits] of Object.entries(LIMITS) as [WindowName, typeof LIMITS[WindowName]][]) {
    const key = windowKey(userId, window);
    const raw = await env.KV.get(key);
    if (!raw) continue;

    const counters = JSON.parse(raw);
    if (counters.req > limits.maxRequests) {
      return { ok: false, window, resetsIn: timeUntilReset(window) };
    }
  }
  return { ok: true };
}

export async function incrementCounters(userId: string, bytesIn: number, bytesOut: number, env: Env): Promise<void> {
  for (const [window, limits] of Object.entries(LIMITS) as [WindowName, typeof LIMITS[WindowName]][]) {
    const key = windowKey(userId, window);
    const raw = await env.KV.get(key);
    const counters = raw ? JSON.parse(raw) : { req: 0, in: 0, out: 0 };

    counters.req += 1;
    counters.in += bytesIn;
    counters.out += bytesOut;

    await env.KV.put(key, JSON.stringify(counters), { expirationTtl: limits.ttl });
  }
}
