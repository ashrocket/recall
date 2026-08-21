// Router for /v1/memory_stores/**.
//
// Verb table, taken from the shipped SDK client rather than the bundled docs:
//
//   POST   /v1/memory_stores                                    create store
//   GET    /v1/memory_stores                                    list stores
//   GET    /v1/memory_stores/{id}                               retrieve store
//   POST   /v1/memory_stores/{id}                               update store
//   DELETE /v1/memory_stores/{id}                               delete store
//   POST   /v1/memory_stores/{id}/archive                       archive store
//   POST   /v1/memory_stores/{id}/memories                      create memory
//   GET    /v1/memory_stores/{id}/memories                      list memories
//   GET    /v1/memory_stores/{id}/memories/{mid}                retrieve memory
//   POST   /v1/memory_stores/{id}/memories/{mid}                update memory  <- POST, not PATCH
//   DELETE /v1/memory_stores/{id}/memories/{mid}                delete memory
//   GET    /v1/memory_stores/{id}/memory_versions               list versions
//   GET    /v1/memory_stores/{id}/memory_versions/{vid}         retrieve version
//   POST   /v1/memory_stores/{id}/memory_versions/{vid}/redact  redact version

import type { MemoryEnv, Actor } from "./types";
import { err } from "./errors";
import {
  createStore,
  listStores,
  retrieveStore,
  updateStore,
  archiveStore,
  deleteStore,
} from "./stores";
import {
  createMemory,
  listMemories,
  retrieveMemory,
  updateMemory,
  deleteMemory,
} from "./memories";
import { listVersions, retrieveVersion, redactVersion } from "./versions";

/** The beta this surface ships under. The Managed Agents beta does not cover it. */
export const MEMORY_BETA = "agent-memory-2026-07-22";

export async function handleMemory(
  request: Request,
  url: URL,
  userId: string,
  env: MemoryEnv,
): Promise<Response> {
  if (!env.DB) return err.internal("memory storage is not configured");

  const actor: Actor = { userId, type: "api_actor", id: userId };
  const method = request.method;

  // ["v1","memory_stores", storeId?, sub?, subId?, action?]
  const seg = url.pathname.split("/").filter(Boolean);
  const storeId = seg[2];
  const sub = seg[3];
  const subId = seg[4];
  const action = seg[5];

  if (!storeId) {
    if (method === "POST") return createStore(request, actor, env);
    if (method === "GET") return listStores(url, actor, env);
    return err.invalidRequest(`method ${method} is not allowed on /v1/memory_stores`);
  }

  if (!sub) {
    if (method === "GET") return retrieveStore(storeId, actor, env);
    if (method === "POST") return updateStore(storeId, request, actor, env);
    if (method === "DELETE") return deleteStore(storeId, actor, env);
    return err.invalidRequest(`method ${method} is not allowed on this resource`);
  }

  if (sub === "archive" && method === "POST") {
    return archiveStore(storeId, actor, env);
  }

  if (sub === "memories") {
    if (!subId) {
      if (method === "POST") return createMemory(storeId, request, actor, env);
      if (method === "GET") return listMemories(storeId, url, actor, env);
    } else {
      if (method === "GET") return retrieveMemory(storeId, subId, url, actor, env);
      if (method === "POST") return updateMemory(storeId, subId, request, actor, env);
      if (method === "DELETE") return deleteMemory(storeId, subId, url, actor, env);
    }
    return err.invalidRequest(`method ${method} is not allowed on this resource`);
  }

  if (sub === "memory_versions") {
    if (!subId) {
      if (method === "GET") return listVersions(storeId, url, actor, env);
    } else if (action === "redact") {
      if (method === "POST") return redactVersion(storeId, subId, actor, env);
    } else {
      if (method === "GET") return retrieveVersion(storeId, subId, actor, env);
    }
    return err.invalidRequest(`method ${method} is not allowed on this resource`);
  }

  return err.notFound("resource not found");
}
