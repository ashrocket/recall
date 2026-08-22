// /v1/memory_stores — store CRUD.
//
// Verbs follow the SHIPPED SDK, not the bundled docs: every mutation is POST. There is
// no PATCH anywhere on this surface.

import type { MemoryEnv, Actor } from "./types";
import { err, ok, LIMITS } from "./errors";
import { newStoreId, now } from "./ids";

interface StoreRow {
  id: string;
  owner_user_id: string;
  project_id: string | null;
  scope: string;
  name: string;
  description: string;
  metadata_json: string;
  mount: string;
  prompt_index: string | null;
  partition_path: string;
  memory_count: number;
  bytes_total: number;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  deleted_at: string | null;
}

/** Wire representation. Field names match the documented memory-store object. */
export function serializeStore(row: StoreRow) {
  return {
    type: "memory_store",
    id: row.id,
    name: row.name,
    description: row.description,
    metadata: JSON.parse(row.metadata_json || "{}"),
    memory_count: row.memory_count,
    created_at: row.created_at,
    updated_at: row.updated_at,
    archived_at: row.archived_at,
  };
}

/** Loads a live store the caller owns. Ownership failures read as 404, not 403. */
export async function loadStore(
  storeId: string,
  actor: Actor,
  env: MemoryEnv,
): Promise<StoreRow | null> {
  const row = await env.DB.prepare(
    `SELECT * FROM stores WHERE id = ? AND owner_user_id = ? AND deleted_at IS NULL`,
  )
    .bind(storeId, actor.userId)
    .first<StoreRow>();
  return row ?? null;
}

function validName(name: unknown): name is string {
  if (typeof name !== "string") return false;
  if (name.length < 1 || name.length > 255) return false;
  return !/[\u0000-\u001f\u007f]/.test(name);
}

export async function createStore(request: Request, actor: Actor, env: MemoryEnv) {
  const body = (await request.json().catch(() => null)) as Record<string, unknown> | null;
  if (!body) return err.invalidRequest("request body must be a JSON object");

  const { name, description, metadata, project_id, scope } = body;
  if (!validName(name)) return err.invalidRequest("name must be a string of 1 to 255 characters");

  if (description !== undefined && typeof description !== "string") {
    return err.invalidRequest("description must be a string");
  }
  if (metadata !== undefined && (typeof metadata !== "object" || metadata === null || Array.isArray(metadata))) {
    return err.invalidRequest("metadata must be an object");
  }
  if (metadata && Object.keys(metadata as object).length > 16) {
    return err.invalidRequest("metadata must have at most 16 entries");
  }
  if (scope !== undefined && scope !== "team" && scope !== "user") {
    return err.invalidRequest('scope must be "team" or "user"');
  }
  if (project_id !== undefined && typeof project_id !== "string") {
    return err.invalidRequest("project_id must be a string");
  }

  const id = newStoreId();
  const ts = now();
  const partitionPath = `/v1/code/memory/grouping/${id}`;

  try {
    await env.DB.prepare(
      `INSERT INTO stores
         (id, owner_user_id, project_id, scope, name, description, metadata_json,
          partition_path, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    )
      .bind(
        id,
        actor.userId,
        (project_id as string) ?? null,
        (scope as string) ?? "team",
        name,
        (description as string) ?? "",
        JSON.stringify(metadata ?? {}),
        partitionPath,
        ts,
        ts,
      )
      .run();
  } catch (e) {
    // The partial unique index on (owner, project, scope) is what fires here.
    if (String(e).includes("UNIQUE")) {
      return err.invalidRequest("a store already exists for that project and scope");
    }
    throw e;
  }

  const row = await loadStore(id, actor, env);
  return ok(serializeStore(row!), 201);
}

export async function listStores(url: URL, actor: Actor, env: MemoryEnv) {
  const includeArchived = url.searchParams.get("include_archived") === "true";
  const limit = Math.min(
    parseInt(url.searchParams.get("limit") ?? String(LIMITS.DEFAULT_LIST_LIMIT), 10) ||
      LIMITS.DEFAULT_LIST_LIMIT,
    LIMITS.MAX_LIST_LIMIT,
  );
  const after = url.searchParams.get("after_id");

  const clauses = ["owner_user_id = ?", "deleted_at IS NULL"];
  const binds: unknown[] = [actor.userId];
  if (!includeArchived) clauses.push("archived_at IS NULL");
  if (after) {
    clauses.push("(created_at, id) < (SELECT created_at, id FROM stores WHERE id = ?)");
    binds.push(after);
  }

  const { results } = await env.DB.prepare(
    `SELECT * FROM stores WHERE ${clauses.join(" AND ")}
     ORDER BY created_at DESC, id DESC LIMIT ?`,
  )
    .bind(...binds, limit + 1)
    .all<StoreRow>();

  const rows = results ?? [];
  const hasMore = rows.length > limit;
  const page = hasMore ? rows.slice(0, limit) : rows;

  return ok({
    data: page.map(serializeStore),
    has_more: hasMore,
    first_id: page[0]?.id ?? null,
    last_id: page[page.length - 1]?.id ?? null,
  });
}

export async function retrieveStore(storeId: string, actor: Actor, env: MemoryEnv) {
  const row = await loadStore(storeId, actor, env);
  if (!row) return err.notFound("memory store not found");
  return ok(serializeStore(row));
}

export async function updateStore(
  storeId: string,
  request: Request,
  actor: Actor,
  env: MemoryEnv,
) {
  const row = await loadStore(storeId, actor, env);
  if (!row) return err.notFound("memory store not found");
  if (row.archived_at) return err.invalidRequest("cannot modify archived resource: memory store");

  const body = (await request.json().catch(() => null)) as Record<string, unknown> | null;
  if (!body) return err.invalidRequest("request body must be a JSON object");

  const sets: string[] = [];
  const binds: unknown[] = [];

  if (body.name !== undefined) {
    if (!validName(body.name)) return err.invalidRequest("name must be a string of 1 to 255 characters");
    sets.push("name = ?");
    binds.push(body.name);
  }
  if (body.description !== undefined) {
    if (typeof body.description !== "string") return err.invalidRequest("description must be a string");
    sets.push("description = ?");
    binds.push(body.description);
  }
  if (body.metadata !== undefined) {
    if (typeof body.metadata !== "object" || body.metadata === null || Array.isArray(body.metadata)) {
      return err.invalidRequest("metadata must be an object");
    }
    sets.push("metadata_json = ?");
    binds.push(JSON.stringify(body.metadata));
  }

  if (sets.length === 0) return ok(serializeStore(row));

  sets.push("updated_at = ?");
  binds.push(now());

  await env.DB.prepare(`UPDATE stores SET ${sets.join(", ")} WHERE id = ?`)
    .bind(...binds, storeId)
    .run();

  return ok(serializeStore((await loadStore(storeId, actor, env))!));
}

/** Archive is terminal: the store becomes read-only and there is no unarchive. */
export async function archiveStore(storeId: string, actor: Actor, env: MemoryEnv) {
  const row = await loadStore(storeId, actor, env);
  if (!row) return err.notFound("memory store not found");
  if (row.archived_at) return ok(serializeStore(row));

  const ts = now();
  await env.DB.prepare(`UPDATE stores SET archived_at = ?, updated_at = ? WHERE id = ?`)
    .bind(ts, ts, storeId)
    .run();

  return ok(serializeStore((await loadStore(storeId, actor, env))!));
}

/**
 * Soft delete. The store row is tombstoned first so trg_versions_no_delete permits the
 * version rows to go, then memories, versions, and blobs are removed.
 */
export async function deleteStore(storeId: string, actor: Actor, env: MemoryEnv) {
  const row = await loadStore(storeId, actor, env);
  if (!row) return err.notFound("memory store not found");

  await env.DB.prepare(`UPDATE stores SET deleted_at = ? WHERE id = ?`).bind(now(), storeId).run();

  const { results } = await env.DB.prepare(`SELECT sha256 FROM blobs WHERE store_id = ?`)
    .bind(storeId)
    .all<{ sha256: string }>();

  await env.DB.batch([
    env.DB.prepare(`DELETE FROM memory_versions WHERE store_id = ?`).bind(storeId),
    env.DB.prepare(`DELETE FROM memories WHERE store_id = ?`).bind(storeId),
    env.DB.prepare(`DELETE FROM blobs WHERE store_id = ?`).bind(storeId),
  ]);

  for (const b of results ?? []) {
    await env.BUCKET.delete(`mem/${storeId}/${b.sha256}`);
  }

  return ok({ id: storeId, type: "memory_store", deleted: true });
}
