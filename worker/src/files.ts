import type { Env } from "./index";
import { incrementCounters } from "./rate-limiter";
import { sha256Hex } from "./memory/ids";
import { scanForSecret } from "./memory/secrets";

// The /v1/files surface, with two primitives borrowed from the memory-store model:
//
//   * content_sha256 optimistic concurrency. A PUT may carry If-Match: <sha> ("only
//     overwrite if the server still holds the version I based my edit on") or
//     If-None-Match: * ("only create if absent"). A mismatch is 412, so two machines
//     editing the same learning no longer silently clobber — the loser is told to pull.
//     Requests without these headers keep the old last-write-wins behaviour.
//
//   * a server-side secret backstop. The client already scans (config.secret_scan), but
//     a buggy or third-party client must not be able to park a credential in synced files
//     that are replayed into later sessions. A hit is 422.

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
  const newSha = await sha256Hex(body);

  // Read the current head once — it answers both preconditions and the idempotency check.
  const head = await env.BUCKET.head(key);
  const existingSha = head?.customMetadata?.content_sha256;

  // Idempotent no-op: the bytes already on the server are exactly these. Return success
  // without a rewrite, regardless of any precondition. This also prevents a spurious 412
  // when a client retries a write that in fact already landed.
  if (existingSha && existingSha === newSha) {
    return jsonResponse({ ok: true, key, size: body.byteLength, content_sha256: newSha, unchanged: true }, 200);
  }

  // Preconditions. If-None-Match: * = create-only. If-Match: <sha> = compare-and-set.
  const ifNoneMatch = request.headers.get("If-None-Match");
  const ifMatch = request.headers.get("If-Match");

  if (ifNoneMatch === "*" && head) {
    return preconditionFailed(key, existingSha, "a file already exists at that path");
  }
  if (ifMatch !== null) {
    if (!head) {
      return preconditionFailed(key, undefined, "no file exists at that path to match against");
    }
    if (existingSha !== ifMatch) {
      return preconditionFailed(key, existingSha, "the file was modified since you last read it");
    }
  }

  // Secret backstop. Scan the decoded text; binary files simply won't match the patterns.
  const text = new TextDecoder("utf-8", { fatal: false, ignoreBOM: false }).decode(body);
  const finding = scanForSecret(text);
  if (finding) {
    return jsonResponse(
      {
        error: "content_secret",
        message:
          "file appears to contain a credential or API key; remove it before syncing. " +
          "If the credential is real, rotate it.",
        detail: { type: finding.type, line: finding.line },
      },
      422,
    );
  }

  const usage = await getStorageUsed(userId, env);
  if (usage + body.byteLength > 10 * 1024 * 1024 * 1024) {
    return jsonResponse({ error: "storage_full", used: usage, cap: 10 * 1024 * 1024 * 1024 }, 507);
  }

  await env.BUCKET.put(key, body, {
    customMetadata: {
      uploaded: new Date().toISOString(),
      size: String(body.byteLength),
      content_sha256: newSha,
    },
  });

  await incrementCounters(userId, body.byteLength, 0, env);

  return jsonResponse({ ok: true, key, size: body.byteLength, content_sha256: newSha }, 200);
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
      // Let the client record the base it just read, so its next push can send If-Match.
      "X-Content-Sha256": object.customMetadata?.content_sha256 || "",
    },
  });
}

async function listFiles(userId: string, url: URL, env: Env): Promise<Response> {
  const after = url.searchParams.get("after");
  const listed = await env.BUCKET.list({
    prefix: `${userId}/`,
    include: ["customMetadata"],
  } as R2ListOptions);

  let files = listed.objects.map((obj) => ({
    path: obj.key.replace(`${userId}/`, ""),
    size: obj.size,
    uploaded: obj.uploaded.toISOString(),
    content_sha256: obj.customMetadata?.content_sha256 || null,
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

/** 412 with the server's current sha so the client can pull, merge, and retry. */
function preconditionFailed(key: string, currentSha: string | undefined, message: string): Response {
  return jsonResponse(
    {
      error: "precondition_failed",
      message,
      key,
      current_content_sha256: currentSha ?? null,
    },
    412,
  );
}

function jsonResponse(data: any, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
