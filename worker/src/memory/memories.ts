// /v1/memory_stores/{store_id}/memories — the surface that actually carries content.
//
// Two rules here are not optional, both learned from how the client reacts:
//
//   1. Never return 409 when the supplied content_sha256 equals the stored one. The
//      client re-reads after a conflict, and if the sha still matches what it sent it
//      raises repeated_spurious_conflict and shows the user a hard error.
//   2. conflicting_path on a 409 must normalise to exactly the path the client asked
//      for, or the client discards conflicting_memory_id and cannot self-heal.
//
// Content lives in R2, content-addressed. D1 holds metadata only.

import type { MemoryEnv, Actor } from "./types";
import { err, ok, MSG, LIMITS } from "./errors";
import { newMemoryId, newVersionId, sha256Hex, utf8Length, now, blobKey } from "./ids";
import { validatePath, ancestorPaths, descendantRange, normalizePath } from "./paths";
import { scanForSecret } from "./secrets";
import { loadStore } from "./stores";

interface MemoryRow {
  id: string;
  store_id: string;
  path: string;
  content_sha256: string;
  content_size_bytes: number;
  head_version_id: string;
  created_at: string;
  updated_at: string;
}

function serializeMemory(row: MemoryRow, content?: string) {
  return {
    type: "memory",
    id: row.id,
    memory_store_id: row.store_id,
    path: row.path,
    content_sha256: row.content_sha256,
    content_size_bytes: row.content_size_bytes,
    created_at: row.created_at,
    updated_at: row.updated_at,
    ...(content !== undefined ? { content } : {}),
  };
}

async function readBlob(storeId: string, sha: string, env: MemoryEnv): Promise<string> {
  const obj = await env.BUCKET.get(blobKey(storeId, sha));
  return obj ? await obj.text() : "";
}

/**
 * Writes content to R2 and bumps the blob refcount.
 *
 * R2 first, then D1. If the subsequent D1 write loses a race the blob is orphaned but
 * harmless — it is content-addressed, so the next writer with the same bytes adopts it,
 * and the refcount sweep reclaims it otherwise.
 */
async function putBlob(storeId: string, content: string, env: MemoryEnv): Promise<string> {
  const sha = await sha256Hex(content);
  const size = utf8Length(content);
  await env.BUCKET.put(blobKey(storeId, sha), content);
  await env.DB.prepare(
    `INSERT INTO blobs (store_id, sha256, size_bytes, refcount, created_at)
     VALUES (?, ?, ?, 1, ?)
     ON CONFLICT(store_id, sha256) DO UPDATE SET refcount = refcount + 1`,
  )
    .bind(storeId, sha, size, now())
    .run();
  return sha;
}

async function releaseBlob(storeId: string, sha: string, env: MemoryEnv): Promise<void> {
  await env.DB.prepare(
    `UPDATE blobs SET refcount = refcount - 1 WHERE store_id = ? AND sha256 = ?`,
  )
    .bind(storeId, sha)
    .run();
}

/** Validates content and returns the client-facing message on failure. */
function checkContent(content: unknown): string | null {
  if (typeof content !== "string") return "content must be a string";
  if (utf8Length(content) > LIMITS.MAX_CONTENT_BYTES) return MSG.CONTENT_TOO_LARGE;
  if (scanForSecret(content)) return MSG.CONTENT_SECRET;
  return null;
}

/**
 * A document and a prefix of its path cannot coexist. Returns a conflicting row when
 * either a descendant or an ancestor of `path` is already occupied.
 */
async function findPrefixConflict(
  storeId: string,
  path: string,
  excludeId: string | null,
  env: MemoryEnv,
): Promise<{ id: string; path: string } | null> {
  const { lo, hi } = descendantRange(path);
  const descendant = await env.DB.prepare(
    `SELECT id, path FROM memories WHERE store_id = ? AND path >= ? AND path < ? AND id != ? LIMIT 1`,
  )
    .bind(storeId, lo, hi, excludeId ?? "")
    .first<{ id: string; path: string }>();
  if (descendant) return descendant;

  const ancestors = ancestorPaths(path);
  if (ancestors.length === 0) return null;

  const placeholders = ancestors.map(() => "?").join(",");
  const ancestor = await env.DB.prepare(
    `SELECT id, path FROM memories
     WHERE store_id = ? AND path IN (${placeholders}) AND id != ? LIMIT 1`,
  )
    .bind(storeId, ...ancestors, excludeId ?? "")
    .first<{ id: string; path: string }>();

  return ancestor ?? null;
}

export async function createMemory(
  storeId: string,
  request: Request,
  actor: Actor,
  env: MemoryEnv,
) {
  const store = await loadStore(storeId, actor, env);
  if (!store) return err.notFound("memory store not found");
  if (store.archived_at) return err.invalidRequest(`${MSG.STORE_ARCHIVED}: memory store`);

  const body = (await request.json().catch(() => null)) as Record<string, unknown> | null;
  if (!body) return err.invalidRequest("request body must be a JSON object");

  const path = typeof body.path === "string" ? normalizePath(body.path) : null;
  if (path === null) return err.invalidRequest("path must be a string");

  const pathError = validatePath(path);
  if (pathError) return err.invalidRequest(pathError);

  const contentError = checkContent(body.content);
  if (contentError) return err.invalidRequest(contentError);
  const content = body.content as string;

  if (store.memory_count >= LIMITS.MAX_MEMORIES_PER_STORE) {
    return err.invalidRequest(MSG.STORE_FULL_COUNT);
  }
  const size = utf8Length(content);
  if (store.bytes_total + size > LIMITS.MAX_STORE_BYTES) {
    return err.invalidRequest(MSG.STORE_FULL_BYTES);
  }

  const prefixConflict = await findPrefixConflict(storeId, path, null, env);
  if (prefixConflict) {
    return err.pathConflict(MSG.PREFIX_CONFLICT, prefixConflict.path, prefixConflict.id);
  }

  const sha = await putBlob(storeId, content, env);
  const id = newMemoryId();
  const versionId = newVersionId();
  const ts = now();

  // ON CONFLICT DO NOTHING makes this the atomic create-if-absent primitive: no
  // read-then-write window for a concurrent writer to slip through.
  const insert = await env.DB.prepare(
    `INSERT INTO memories
       (id, store_id, path, content_sha256, content_size_bytes, head_version_id, created_at, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(store_id, path) DO NOTHING`,
  )
    .bind(id, storeId, path, sha, size, versionId, ts, ts)
    .run();

  if (insert.meta.changes !== 1) {
    await releaseBlob(storeId, sha, env);
    const existing = await env.DB.prepare(
      `SELECT id, path FROM memories WHERE store_id = ? AND path = ?`,
    )
      .bind(storeId, path)
      .first<{ id: string; path: string }>();
    return err.pathConflict(MSG.PATH_CONFLICT, path, existing?.id);
  }

  await env.DB.batch([
    env.DB.prepare(
      `INSERT INTO memory_versions
         (id, store_id, memory_id, operation, path, content_sha256, content_size_bytes,
          actor_type, actor_id, created_at)
       VALUES (?, ?, ?, 'created', ?, ?, ?, ?, ?, ?)`,
    ).bind(versionId, storeId, id, path, sha, size, actor.type, actor.id, ts),
    env.DB.prepare(
      `UPDATE stores SET memory_count = memory_count + 1, bytes_total = bytes_total + ?, updated_at = ?
       WHERE id = ?`,
    ).bind(size, ts, storeId),
  ]);

  const row = await env.DB.prepare(`SELECT * FROM memories WHERE id = ?`)
    .bind(id)
    .first<MemoryRow>();

  return ok(serializeMemory(row!, content), 201);
}

export async function listMemories(
  storeId: string,
  url: URL,
  actor: Actor,
  env: MemoryEnv,
) {
  const store = await loadStore(storeId, actor, env);
  if (!store) return err.notFound("memory store not found");

  const view = url.searchParams.get("view") === "full" ? "full" : "basic";
  const prefix = url.searchParams.get("path_prefix") ?? "/";
  const limit = Math.min(
    parseInt(url.searchParams.get("limit") ?? String(LIMITS.DEFAULT_LIST_LIMIT), 10) ||
      LIMITS.DEFAULT_LIST_LIMIT,
    LIMITS.MAX_LIST_LIMIT,
  );
  const afterPath = url.searchParams.get("after_path");

  const clauses = ["store_id = ?", "path LIKE ?"];
  const binds: unknown[] = [storeId, prefix + "%"];
  if (afterPath) {
    clauses.push("path > ?");
    binds.push(afterPath);
  }

  const { results } = await env.DB.prepare(
    `SELECT * FROM memories WHERE ${clauses.join(" AND ")} ORDER BY path ASC LIMIT ?`,
  )
    .bind(...binds, limit + 1)
    .all<MemoryRow>();

  const rows = results ?? [];
  const hasMore = rows.length > limit;
  const page = hasMore ? rows.slice(0, limit) : rows;

  const data = [];
  for (const row of page) {
    // view=full can carry ~2MB per page — one reason content never lives in D1.
    const content = view === "full" ? await readBlob(storeId, row.content_sha256, env) : undefined;
    data.push(serializeMemory(row, content));
  }

  return ok({
    data,
    has_more: hasMore,
    first_id: page[0]?.id ?? null,
    last_id: page[page.length - 1]?.id ?? null,
  });
}

export async function retrieveMemory(
  storeId: string,
  memoryId: string,
  url: URL,
  actor: Actor,
  env: MemoryEnv,
) {
  const store = await loadStore(storeId, actor, env);
  if (!store) return err.notFound("memory store not found");

  const row = await env.DB.prepare(`SELECT * FROM memories WHERE id = ? AND store_id = ?`)
    .bind(memoryId, storeId)
    .first<MemoryRow>();
  if (!row) return err.notFound("memory not found");

  // retrieve defaults to full, unlike list.
  const view = url.searchParams.get("view") === "basic" ? "basic" : "full";
  const content = view === "full" ? await readBlob(storeId, row.content_sha256, env) : undefined;

  return ok(serializeMemory(row, content));
}

/** POST, not PATCH — the shipped SDK issues this as a POST. */
export async function updateMemory(
  storeId: string,
  memoryId: string,
  request: Request,
  actor: Actor,
  env: MemoryEnv,
) {
  const store = await loadStore(storeId, actor, env);
  if (!store) return err.notFound("memory store not found");
  if (store.archived_at) return err.invalidRequest(`${MSG.STORE_ARCHIVED}: memory store`);

  const row = await env.DB.prepare(`SELECT * FROM memories WHERE id = ? AND store_id = ?`)
    .bind(memoryId, storeId)
    .first<MemoryRow>();
  if (!row) return err.notFound("memory not found");

  const body = (await request.json().catch(() => null)) as Record<string, unknown> | null;
  if (!body) return err.invalidRequest("request body must be a JSON object");

  const newPath = body.path !== undefined ? normalizePath(String(body.path)) : row.path;
  if (body.path !== undefined) {
    const pathError = validatePath(newPath);
    if (pathError) return err.invalidRequest(pathError);
  }

  let newSha = row.content_sha256;
  let newSize = row.content_size_bytes;
  let content: string | undefined;

  if (body.content !== undefined) {
    const contentError = checkContent(body.content);
    if (contentError) return err.invalidRequest(contentError);
    content = body.content as string;
    newSha = await sha256Hex(content);
    newSize = utf8Length(content);
  }

  // --- Precondition handling -----------------------------------------------
  //
  // Rule 2 from the module header, implemented before anything else can 409: if the
  // supplied sha equals what we already store, the client's view is current. Never
  // conflict, even when the precondition would otherwise be judged stale.
  const precondition = body.precondition as { type?: string; content_sha256?: string } | undefined;
  if (precondition) {
    if (precondition.type !== "content_sha256") {
      return err.invalidRequest('precondition.type must be "content_sha256"');
    }
    const supplied = precondition.content_sha256;
    const shaMatches = supplied === row.content_sha256;

    if (!shaMatches) {
      // Rule 1, the carve-out: stored state may already equal what was requested.
      const alreadyThere = newSha === row.content_sha256 && newPath === row.path;
      if (!alreadyThere) return err.preconditionFailed();
    }
  }

  if (newPath !== row.path) {
    const prefixConflict = await findPrefixConflict(storeId, newPath, row.id, env);
    if (prefixConflict) {
      return err.pathConflict(MSG.PREFIX_CONFLICT, prefixConflict.path, prefixConflict.id);
    }
  }

  if (content !== undefined && newSha !== row.content_sha256) {
    await putBlob(storeId, content, env);
  }

  const ts = now();
  const versionId = newVersionId();

  // Single-statement CAS. changes === 0 means someone else moved the row underneath us.
  const update = await env.DB.prepare(
    `UPDATE memories
       SET path = ?, content_sha256 = ?, content_size_bytes = ?, head_version_id = ?, updated_at = ?
     WHERE id = ? AND store_id = ? AND content_sha256 = ?`,
  )
    .bind(newPath, newSha, newSize, versionId, ts, memoryId, storeId, row.content_sha256)
    .run();

  if (update.meta.changes !== 1) {
    if (content !== undefined && newSha !== row.content_sha256) {
      await releaseBlob(storeId, newSha, env);
    }
    const fresh = await env.DB.prepare(`SELECT * FROM memories WHERE id = ? AND store_id = ?`)
      .bind(memoryId, storeId)
      .first<MemoryRow>();
    if (!fresh) return err.notFound("memory not found");

    // A rename onto an occupied path surfaces as a path conflict, not a precondition failure.
    if (fresh.path !== newPath) {
      const occupant = await env.DB.prepare(
        `SELECT id, path FROM memories WHERE store_id = ? AND path = ?`,
      )
        .bind(storeId, newPath)
        .first<{ id: string; path: string }>();
      if (occupant) return err.pathConflict(MSG.PATH_CONFLICT, newPath, occupant.id);
    }

    // Rule 2 again on the retry path: never conflict on content we already agree about.
    if (fresh.content_sha256 === newSha) {
      return ok(serializeMemory(fresh, content));
    }
    return err.preconditionFailed();
  }

  const sizeDelta = newSize - row.content_size_bytes;
  await env.DB.batch([
    env.DB.prepare(
      `INSERT INTO memory_versions
         (id, store_id, memory_id, operation, path, content_sha256, content_size_bytes,
          actor_type, actor_id, created_at)
       VALUES (?, ?, ?, 'modified', ?, ?, ?, ?, ?, ?)`,
    ).bind(versionId, storeId, memoryId, newPath, newSha, newSize, actor.type, actor.id, ts),
    env.DB.prepare(`UPDATE stores SET bytes_total = bytes_total + ?, updated_at = ? WHERE id = ?`).bind(
      sizeDelta,
      ts,
      storeId,
    ),
  ]);

  if (newSha !== row.content_sha256) await releaseBlob(storeId, row.content_sha256, env);

  const updated = await env.DB.prepare(`SELECT * FROM memories WHERE id = ?`)
    .bind(memoryId)
    .first<MemoryRow>();

  return ok(serializeMemory(updated!, content));
}

export async function deleteMemory(
  storeId: string,
  memoryId: string,
  url: URL,
  actor: Actor,
  env: MemoryEnv,
) {
  const store = await loadStore(storeId, actor, env);
  if (!store) return err.notFound("memory store not found");
  if (store.archived_at) return err.invalidRequest(`${MSG.STORE_ARCHIVED}: memory store`);

  const row = await env.DB.prepare(`SELECT * FROM memories WHERE id = ? AND store_id = ?`)
    .bind(memoryId, storeId)
    .first<MemoryRow>();
  if (!row) return err.notFound("memory not found");

  const expected = url.searchParams.get("expected_content_sha256");
  const ts = now();

  const del = expected
    ? await env.DB.prepare(
        `DELETE FROM memories WHERE id = ? AND store_id = ? AND content_sha256 = ?`,
      )
        .bind(memoryId, storeId, expected)
        .run()
    : await env.DB.prepare(`DELETE FROM memories WHERE id = ? AND store_id = ?`)
        .bind(memoryId, storeId)
        .run();

  if (del.meta.changes !== 1) return err.preconditionFailed();

  await env.DB.batch([
    env.DB.prepare(
      `INSERT INTO memory_versions
         (id, store_id, memory_id, operation, path, content_sha256, content_size_bytes,
          actor_type, actor_id, created_at)
       VALUES (?, ?, ?, 'deleted', ?, NULL, NULL, ?, ?, ?)`,
    ).bind(newVersionId(), storeId, memoryId, row.path, actor.type, actor.id, ts),
    env.DB.prepare(
      `UPDATE stores SET memory_count = memory_count - 1, bytes_total = bytes_total - ?, updated_at = ?
       WHERE id = ?`,
    ).bind(row.content_size_bytes, ts, storeId),
  ]);

  await releaseBlob(storeId, row.content_sha256, env);

  return ok({ id: memoryId, type: "memory", deleted: true });
}
