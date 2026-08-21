// /v1/memory_stores/{store_id}/memory_versions — the audit and redaction surface.
//
// Versions are insert-only. Redaction is the single legal update and the DB triggers
// enforce that; the handler below only decides who may ask for it.

import type { MemoryEnv, Actor } from "./types";
import { err, ok, LIMITS } from "./errors";
import { now, blobKey } from "./ids";
import { loadStore } from "./stores";

interface VersionRow {
  seq: number;
  id: string;
  store_id: string;
  memory_id: string;
  operation: string;
  path: string | null;
  content_sha256: string | null;
  content_size_bytes: number | null;
  actor_type: string;
  actor_id: string;
  created_at: string;
  redacted_at: string | null;
  redacted_actor_type: string | null;
  redacted_actor_id: string | null;
}

function serializeVersion(row: VersionRow, content?: string) {
  return {
    type: "memory_version",
    id: row.id,
    memory_store_id: row.store_id,
    memory_id: row.memory_id,
    operation: row.operation,
    path: row.path,
    content_sha256: row.content_sha256,
    content_size_bytes: row.content_size_bytes,
    created_by: { type: row.actor_type, id: row.actor_id },
    created_at: row.created_at,
    redacted_at: row.redacted_at,
    ...(row.redacted_at
      ? { redacted_by: { type: row.redacted_actor_type, id: row.redacted_actor_id } }
      : {}),
    ...(content !== undefined ? { content } : {}),
  };
}

export async function listVersions(
  storeId: string,
  url: URL,
  actor: Actor,
  env: MemoryEnv,
) {
  const store = await loadStore(storeId, actor, env);
  if (!store) return err.notFound("memory store not found");

  const limit = Math.min(
    parseInt(url.searchParams.get("limit") ?? String(LIMITS.DEFAULT_LIST_LIMIT), 10) ||
      LIMITS.DEFAULT_LIST_LIMIT,
    LIMITS.MAX_LIST_LIMIT,
  );

  const clauses = ["store_id = ?"];
  const binds: unknown[] = [storeId];

  const memoryId = url.searchParams.get("memory_id");
  if (memoryId) {
    clauses.push("memory_id = ?");
    binds.push(memoryId);
  }
  const operation = url.searchParams.get("operation");
  if (operation) {
    if (!["created", "modified", "deleted"].includes(operation)) {
      return err.invalidRequest("operation must be created, modified, or deleted");
    }
    clauses.push("operation = ?");
    binds.push(operation);
  }
  const gte = url.searchParams.get("created_at_gte");
  if (gte) {
    clauses.push("created_at >= ?");
    binds.push(gte);
  }
  const lte = url.searchParams.get("created_at_lte");
  if (lte) {
    clauses.push("created_at <= ?");
    binds.push(lte);
  }
  // seq is monotonic, so it is a stable cursor even as rows are inserted.
  const afterSeq = url.searchParams.get("after_seq");
  if (afterSeq) {
    clauses.push("seq < ?");
    binds.push(parseInt(afterSeq, 10));
  }

  const { results } = await env.DB.prepare(
    `SELECT * FROM memory_versions WHERE ${clauses.join(" AND ")} ORDER BY seq DESC LIMIT ?`,
  )
    .bind(...binds, limit + 1)
    .all<VersionRow>();

  const rows = results ?? [];
  const hasMore = rows.length > limit;
  const page = hasMore ? rows.slice(0, limit) : rows;

  const view = url.searchParams.get("view") === "full" ? "full" : "basic";
  const data = [];
  for (const row of page) {
    let content: string | undefined;
    if (view === "full" && row.content_sha256 && !row.redacted_at) {
      const obj = await env.BUCKET.get(blobKey(storeId, row.content_sha256));
      content = obj ? await obj.text() : "";
    }
    data.push(serializeVersion(row, content));
  }

  return ok({
    data,
    has_more: hasMore,
    first_id: page[0]?.id ?? null,
    last_id: page[page.length - 1]?.id ?? null,
    next_cursor: hasMore ? String(page[page.length - 1]?.seq) : null,
  });
}

export async function retrieveVersion(
  storeId: string,
  versionId: string,
  actor: Actor,
  env: MemoryEnv,
) {
  const store = await loadStore(storeId, actor, env);
  if (!store) return err.notFound("memory store not found");

  const row = await env.DB.prepare(
    `SELECT * FROM memory_versions WHERE id = ? AND store_id = ?`,
  )
    .bind(versionId, storeId)
    .first<VersionRow>();
  if (!row) return err.notFound("memory version not found");

  let content: string | undefined;
  if (row.content_sha256 && !row.redacted_at) {
    const obj = await env.BUCKET.get(blobKey(storeId, row.content_sha256));
    content = obj ? await obj.text() : "";
  }

  return ok(serializeVersion(row, content));
}

/**
 * Redaction clears content, hash, size, and path while preserving actor and timestamps.
 *
 * The blob is only removed once nothing references it — a later version may share the
 * same content_sha256, and content-addressing means deleting eagerly would corrupt them.
 */
export async function redactVersion(
  storeId: string,
  versionId: string,
  actor: Actor,
  env: MemoryEnv,
) {
  const store = await loadStore(storeId, actor, env);
  if (!store) return err.notFound("memory store not found");

  const row = await env.DB.prepare(
    `SELECT * FROM memory_versions WHERE id = ? AND store_id = ?`,
  )
    .bind(versionId, storeId)
    .first<VersionRow>();
  if (!row) return err.notFound("memory version not found");
  if (row.redacted_at) return ok(serializeVersion(row));

  const sha = row.content_sha256;
  const ts = now();

  await env.DB.prepare(
    `UPDATE memory_versions
       SET path = NULL, content_sha256 = NULL, content_size_bytes = NULL,
           redacted_at = ?, redacted_actor_type = ?, redacted_actor_id = ?
     WHERE id = ? AND store_id = ?`,
  )
    .bind(ts, actor.type, actor.id, versionId, storeId)
    .run();

  if (sha) {
    await env.DB.prepare(
      `UPDATE blobs SET refcount = refcount - 1 WHERE store_id = ? AND sha256 = ?`,
    )
      .bind(storeId, sha)
      .run();

    const stillReferenced = await env.DB.prepare(
      `SELECT 1 FROM memories WHERE store_id = ? AND content_sha256 = ?
       UNION ALL
       SELECT 1 FROM memory_versions WHERE store_id = ? AND content_sha256 = ? LIMIT 1`,
    )
      .bind(storeId, sha, storeId, sha)
      .first();

    if (!stillReferenced) await env.BUCKET.delete(blobKey(storeId, sha));
  }

  const fresh = await env.DB.prepare(`SELECT * FROM memory_versions WHERE id = ?`)
    .bind(versionId)
    .first<VersionRow>();

  return ok(serializeVersion(fresh!));
}
