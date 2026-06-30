// worker/src/export.ts
import type { Env } from "./index";

export async function handleExport(userId: string, env: Env): Promise<Response> {
  const now = new Date();
  const exportKey = `export:${userId}:${now.toISOString().slice(0, 10)}`;
  const exported = await env.KV.get(exportKey);

  if (exported) {
    return new Response(JSON.stringify({ error: "export_limit", message: "1 export per day" }), {
      status: 429,
      headers: { "Content-Type": "application/json" },
    });
  }

  const listed = await env.BUCKET.list({ prefix: `${userId}/` });
  const files = listed.objects.map((obj) => ({
    path: obj.key.replace(`${userId}/`, ""),
    size: obj.size,
    uploaded: obj.uploaded.toISOString(),
  }));

  await env.KV.put(exportKey, "1", { expirationTtl: 86400 });

  return new Response(JSON.stringify({
    export: true,
    files,
    count: files.length,
    total_bytes: files.reduce((sum, f) => sum + f.size, 0),
    message: "Use /v1/files/{path} to download each file",
  }), {
    headers: { "Content-Type": "application/json" },
  });
}
