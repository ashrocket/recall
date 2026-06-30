import type { Env } from "./index";

interface AuthSuccess {
  ok: true;
  userId: string;
  tier: string;
}

interface AuthFailure {
  ok: false;
  status: number;
  error: string;
}

type AuthResult = AuthSuccess | AuthFailure;

export async function hashApiKey(rawKey: string, salt: string): Promise<string> {
  const encoder = new TextEncoder();
  const data = encoder.encode(rawKey + salt);
  const hashBuffer = await crypto.subtle.digest("SHA-256", data);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map((b) => b.toString(16).padStart(2, "0")).join("");
}

export async function authenticate(request: Request, env: Env): Promise<AuthResult> {
  const authHeader = request.headers.get("Authorization");
  if (!authHeader?.startsWith("Bearer ")) {
    return { ok: false, status: 401, error: "missing_api_key" };
  }

  const rawKey = authHeader.slice(7);
  const keyHash = await hashApiKey(rawKey, env.API_KEY_SALT);
  const record = await env.KV.get(`key:${keyHash}`);

  if (!record) {
    return { ok: false, status: 401, error: "invalid_api_key" };
  }

  const data = JSON.parse(record);

  if (data.status === "expired" || data.status === "deleted") {
    return { ok: false, status: 403, error: `account_${data.status}` };
  }
  if (data.status === "inactive") {
    return { ok: false, status: 403, error: "account_inactive" };
  }

  return { ok: true, userId: data.user_id, tier: data.tier || "lite" };
}

export async function handleRotateKey(userId: string, env: Env): Promise<Response> {
  const rawBytes = new Uint8Array(32);
  crypto.getRandomValues(rawBytes);
  const newRawKey = "sk_recall_" + Array.from(rawBytes).map(b => b.toString(16).padStart(2, "0")).join("");
  const newHash = await hashApiKey(newRawKey, env.API_KEY_SALT);

  const oldKeys = await env.KV.list({ prefix: `key:` });
  for (const key of oldKeys.keys) {
    const val = await env.KV.get(key.name);
    if (val) {
      const data = JSON.parse(val);
      if (data.user_id === userId) {
        await env.KV.put(`key:${newHash}`, JSON.stringify(data));
        await env.KV.delete(key.name);
        break;
      }
    }
  }

  return new Response(JSON.stringify({ api_key: newRawKey }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
