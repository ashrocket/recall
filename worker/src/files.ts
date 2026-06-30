import type { Env } from "./index";
import { incrementCounters } from "./rate-limiter";

export async function handleFiles(request: Request, url: URL, userId: string, env: Env): Promise<Response> {
  const filePath = url.pathname.replace(/^\/v1\/files\/?/, "");
  const fullKey = `${userId}/${filePath}`;

  switch (request.method) {
    case "PUT":
      return putFile(fullKey, userId, request, env);
    case "GET":
      if (!filePath) return listFiles(userId, url, env);
      if (filePath.endsWith("/versions")) return listVersions(fullKey.replace(/\/versions$/, ""), env);
      return getFile(fullKey, url, env);
    case "DELETE":
      if (filePath.endsWith("/versions")) return trimVersions(fullKey.replace(/\/versions$/, ""), url, env);
      return deleteFile(fullKey, env);
    default:
      return jsonResponse({ error: "method_not_allowed" }, 405);
  }
}

async function putFile(key: string, userId: string, request: Request, env: Env): Promise<Response> {
  const body = await request.arrayBuffer();

  const usage = await getStorageUsed(userId, env);
  if (usage + body.byteLength > 10 * 1024 * 1024 * 1024) {
    return jsonResponse({ error: "storage_full", used: usage, cap: 10 * 1024 * 1024 * 1024 }, 507);
  }

  await env.BUCKET.put(key, body, {
    customMetadata: {
      uploaded: new Date().toISOString(),
      size: String(body.byteLength),
    },
  });

  await incrementCounters(userId, body.byteLength, 0, env);

  return jsonResponse({ ok: true, key, size: body.byteLength }, 200);
}

async function getFile(key: string, url: URL, env: Env): Promise<Response> {
  const object = await env.BUCKET.get(key);
  if (!object) {
    return jsonResponse({ error: "not_found" }, 404);
  }

  const body = await object.arrayBuffer();
  return new Response(body, {
    headers: {
      "Content-Type": "application/x-yaml",
      "X-Version": object.version || "1",
      "X-Uploaded": object.customMetadata?.uploaded || "",
    },
  });
}

async function listFiles(userId: string, url: URL, env: Env): Promise<Response> {
  const after = url.searchParams.get("after");
  const listed = await env.BUCKET.list({ prefix: `${userId}/` });

  let files = listed.objects.map((obj) => ({
    path: obj.key.replace(`${userId}/`, ""),
    size: obj.size,
    uploaded: obj.uploaded.toISOString(),
  }));

  if (after) {
    const afterDate = new Date(after);
    files = files.filter((f) => new Date(f.uploaded) > afterDate);
  }

  return jsonResponse({ files, count: files.length });
}

async function listVersions(key: string, env: Env): Promise<Response> {
  const versions = await env.BUCKET.list({ prefix: key } as R2ListOptions);
  return jsonResponse({
    versions: versions.objects.map((v) => ({
      version: v.version,
      size: v.size,
      uploaded: v.uploaded.toISOString(),
    })),
  });
}

async function trimVersions(key: string, url: URL, env: Env): Promise<Response> {
  const keep = parseInt(url.searchParams.get("keep") || "3", 10);
  const versions = await env.BUCKET.list({ prefix: key });
  const sorted = versions.objects.sort((a, b) => b.uploaded.getTime() - a.uploaded.getTime());
  let deleted = 0;

  for (const obj of sorted.slice(keep)) {
    await env.BUCKET.delete(obj.key);
    deleted++;
  }

  return jsonResponse({ ok: true, kept: keep, deleted });
}

async function deleteFile(key: string, env: Env): Promise<Response> {
  await env.BUCKET.delete(key);
  return jsonResponse({ ok: true });
}

async function getStorageUsed(userId: string, env: Env): Promise<number> {
  const listed = await env.BUCKET.list({ prefix: `${userId}/` });
  return listed.objects.reduce((sum, obj) => sum + obj.size, 0);
}

function jsonResponse(data: any, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
