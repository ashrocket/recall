-- recall memory stores — D1 schema
--
-- Apply with:
--   wrangler d1 migrations apply recall-memory --remote
--
-- Design notes that are load-bearing:
--   * Memory CONTENT never lives here. It goes to R2 at mem/<store_id>/<content_sha256>.
--     One `view=full` list page can carry ~2MB of content; D1 is the wrong home for it.
--   * memories(store_id, path) UNIQUE is not just an index — it IS the 409
--     memory_path_conflict_error behaviour, enforced by the database rather than by a
--     read-then-write race in the handler.
--   * memory_versions is insert-only. Redaction is the single legal update, and the
--     trigger below makes that a schema invariant instead of a convention.

-- ---------------------------------------------------------------------------
-- projects — a git repo (or a remote-less local checkout) owned by one user
-- ---------------------------------------------------------------------------
CREATE TABLE projects (
  owner_user_id  TEXT NOT NULL,                 -- matches KV key:<hash> -> user_id
  project_id     TEXT NOT NULL,                 -- 'proj_' + 24 lowercase hex
  origin_kind    TEXT NOT NULL CHECK (origin_kind IN ('git','local')),
  origin_hash    TEXT NOT NULL,                 -- sha256 of canonical origin; raw URL never sent
  display_name   TEXT NOT NULL DEFAULT '',
  created_at     TEXT NOT NULL,                 -- RFC3339 UTC
  PRIMARY KEY (owner_user_id, project_id)
);

CREATE UNIQUE INDEX idx_projects_origin
  ON projects(owner_user_id, origin_kind, origin_hash);

-- ---------------------------------------------------------------------------
-- stores
-- ---------------------------------------------------------------------------
CREATE TABLE stores (
  id              TEXT PRIMARY KEY,             -- 'memstore_' + 26 base32
  owner_user_id   TEXT NOT NULL,
  project_id      TEXT,                         -- NULL when not bound to a project
  scope           TEXT NOT NULL DEFAULT 'team'
                    CHECK (scope IN ('team','user')),
  name            TEXT NOT NULL,
  description     TEXT NOT NULL DEFAULT '',     -- '' when unset, never NULL
  metadata_json   TEXT NOT NULL DEFAULT '{}',
  mount           TEXT NOT NULL DEFAULT 'recall',
  prompt_index    TEXT,
  partition_path  TEXT NOT NULL,                -- '/v1/code/memory/grouping/<id>'
  memory_count    INTEGER NOT NULL DEFAULT 0,
  bytes_total     INTEGER NOT NULL DEFAULT 0,
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL,
  archived_at     TEXT,
  deleted_at      TEXT
);

CREATE UNIQUE INDEX idx_stores_partition ON stores(partition_path);

-- One live store per (user, project, scope).
CREATE UNIQUE INDEX idx_stores_project_scope
  ON stores(owner_user_id, project_id, scope)
  WHERE project_id IS NOT NULL AND deleted_at IS NULL;

-- Keyset pagination for list.
CREATE INDEX idx_stores_owner_created
  ON stores(owner_user_id, created_at DESC, id DESC)
  WHERE deleted_at IS NULL;

-- ---------------------------------------------------------------------------
-- memories — head state only
-- ---------------------------------------------------------------------------
CREATE TABLE memories (
  id                 TEXT PRIMARY KEY,          -- 'mem_' + 26 base32
  store_id           TEXT NOT NULL,
  path               TEXT NOT NULL,             -- NFC, <=1024 bytes, leading '/'
  content_sha256     TEXT NOT NULL,             -- 64 lowercase hex
  content_size_bytes INTEGER NOT NULL,
  head_version_id    TEXT NOT NULL,             -- 'memver_…'
  created_at         TEXT NOT NULL,
  updated_at         TEXT NOT NULL,
  FOREIGN KEY (store_id) REFERENCES stores(id)
);

-- The atomic create-if-absent primitive AND the list keyset index.
CREATE UNIQUE INDEX idx_memories_store_path ON memories(store_id, path);

-- Dedupe, blob refcounting, conflict recovery.
CREATE INDEX idx_memories_store_sha ON memories(store_id, content_sha256);

-- ---------------------------------------------------------------------------
-- memory_versions — insert-only, immutable except for redaction
-- ---------------------------------------------------------------------------
CREATE TABLE memory_versions (
  seq                 INTEGER PRIMARY KEY AUTOINCREMENT,  -- monotonic; the list cursor
  id                  TEXT NOT NULL UNIQUE,               -- 'memver_' + 26 base32
  store_id            TEXT NOT NULL,
  memory_id           TEXT NOT NULL,                      -- valid after the memory is deleted
  operation           TEXT NOT NULL
                        CHECK (operation IN ('created','modified','deleted')),
  path                TEXT,                               -- NULL iff redacted
  content_sha256      TEXT,                               -- NULL when deleted or redacted
  content_size_bytes  INTEGER,                            -- NULL when deleted or redacted
  actor_type          TEXT NOT NULL
                        CHECK (actor_type IN ('api_actor','session_actor','user_actor',
                                              'service_account_actor')),
  actor_id            TEXT NOT NULL,
  created_at          TEXT NOT NULL,
  redacted_at         TEXT,
  redacted_actor_type TEXT,
  redacted_actor_id   TEXT,
  FOREIGN KEY (store_id) REFERENCES stores(id)
);

CREATE INDEX idx_versions_store_seq       ON memory_versions(store_id, seq DESC);
CREATE INDEX idx_versions_memory_seq      ON memory_versions(memory_id, seq DESC);
CREATE INDEX idx_versions_store_op_seq    ON memory_versions(store_id, operation, seq DESC);
CREATE INDEX idx_versions_store_created   ON memory_versions(store_id, created_at DESC, seq DESC);
CREATE INDEX idx_versions_store_actor_seq ON memory_versions(store_id, actor_type, actor_id, seq DESC);

-- Immutability as a schema invariant. Redaction may null path/content_sha256/
-- content_size_bytes and set the redacted_* columns; nothing else may change, and a
-- row that is already redacted may not be updated again.
CREATE TRIGGER trg_versions_immutable
BEFORE UPDATE ON memory_versions
FOR EACH ROW
WHEN OLD.redacted_at IS NOT NULL
  OR NEW.id         <> OLD.id
  OR NEW.store_id   <> OLD.store_id
  OR NEW.memory_id  <> OLD.memory_id
  OR NEW.operation  <> OLD.operation
  OR NEW.created_at <> OLD.created_at
  OR NEW.actor_type <> OLD.actor_type
  OR NEW.actor_id   <> OLD.actor_id
BEGIN
  SELECT RAISE(ABORT, 'memory_versions rows are immutable except for redaction');
END;

-- Versions are removed only when their store is being torn down.
CREATE TRIGGER trg_versions_no_delete
BEFORE DELETE ON memory_versions
FOR EACH ROW
WHEN (SELECT deleted_at FROM stores WHERE id = OLD.store_id) IS NULL
BEGIN
  SELECT RAISE(ABORT, 'memory_versions rows are deleted only with their store');
END;

-- ---------------------------------------------------------------------------
-- blobs — refcounted R2 objects at mem/<store_id>/<sha256>
-- ---------------------------------------------------------------------------
CREATE TABLE blobs (
  store_id   TEXT NOT NULL,
  sha256     TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  refcount   INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  PRIMARY KEY (store_id, sha256)
);

CREATE INDEX idx_blobs_orphan ON blobs(created_at) WHERE refcount <= 0;

-- ---------------------------------------------------------------------------
-- tokens — enumerable index + revocation log.
-- KV key:<hash> stays the hot-path authority; this table exists so rotation does
-- not need a KV scan and so project-scoped keys can be listed and revoked.
-- ---------------------------------------------------------------------------
CREATE TABLE tokens (
  key_hash     TEXT PRIMARY KEY,                -- SHA-256(raw + API_KEY_SALT), lowercase hex
  user_id      TEXT NOT NULL,
  scope        TEXT NOT NULL DEFAULT 'account', -- 'account' | 'project:<project_id>'
  label        TEXT NOT NULL DEFAULT '',
  created_at   TEXT NOT NULL,
  last_used_at TEXT,
  revoked_at   TEXT
);

CREATE INDEX idx_tokens_user ON tokens(user_id, revoked_at);
