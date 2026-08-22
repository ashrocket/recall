// Error envelopes for the /v1/memory_stores/** surface.
//
// These messages are compared by EXACT EQUALITY by the Claude Code client, and the
// whole mapping is gated on error.type === "invalid_request_error". A 400 emitted with
// any other error.type makes every string here dead and the client degrades to a
// generic permanent http_400. Never inline these strings at a call site.

export const MSG = {
  // Path validation — order matters; see paths.ts.
  PATH_LEADING_SLASH: 'path must start with "/"',
  PATH_TOO_LONG: "path must be at most 1024 bytes",
  PATH_TOO_DEEP: "path must be at most 20 segments deep",
  PATH_DOT_SEGMENT: "path must not contain . or .. segments",
  PATH_EMPTY_SEGMENT: "path must not contain empty segments",
  PATH_CONTROL_CHARS: "path must not contain control or format characters",
  PATH_NOT_NFC: "path must be NFC-normalized",

  // Content and store limits.
  CONTENT_TOO_LARGE: "content must be at most 102400 bytes",
  STORE_FULL_COUNT: "memory store has reached its memory limit",
  STORE_FULL_BYTES: "memory store has reached its size limit",
  CONTENT_SECRET:
    "memory content appears to contain a credential or API key; remove it before writing. " +
    "If the credential is real, rotate it.",

  // The client matches this by PREFIX, not equality.
  STORE_ARCHIVED: "cannot modify archived resource",

  // Conflicts.
  PATH_CONFLICT: "a memory already exists at that path",
  PREFIX_CONFLICT: "a document and a prefix of its path cannot coexist",
  PRECONDITION_FAILED: "the supplied content_sha256 does not match the stored content",
} as const;

export const LIMITS = {
  MAX_CONTENT_BYTES: 102_400,
  MAX_PATH_BYTES: 1024,
  MAX_PATH_SEGMENTS: 20,
  MAX_MEMORIES_PER_STORE: 2_000,
  MAX_STORE_BYTES: 64 * 1024 * 1024,
  MAX_LIST_LIMIT: 100,
  DEFAULT_LIST_LIMIT: 20,
} as const;

type ErrorType =
  | "invalid_request_error"
  | "authentication_error"
  | "permission_error"
  | "not_found_error"
  | "memory_path_conflict_error"
  | "memory_precondition_failed_error"
  | "rate_limit_error"
  | "api_error"
  | "overloaded_error";

interface ErrorExtras {
  conflicting_memory_id?: string;
  conflicting_path?: string;
}

function envelope(type: ErrorType, message: string, extras: ErrorExtras = {}) {
  return { type: "error", error: { type, message, ...extras } };
}

function respond(status: number, type: ErrorType, message: string, extras: ErrorExtras = {}) {
  return new Response(JSON.stringify(envelope(type, message, extras)), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export const err = {
  /** 400 — the only status whose messages the client maps to specific reasons. */
  invalidRequest: (message: string) => respond(400, "invalid_request_error", message),

  unauthorized: (message = "invalid or missing API key") =>
    respond(401, "authentication_error", message),

  forbidden: (message = "this API key cannot access that resource") =>
    respond(403, "permission_error", message),

  notFound: (message = "resource not found") => respond(404, "not_found_error", message),

  /**
   * 409 path conflict.
   *
   * conflicting_path MUST normalise to exactly the path the client asked for, or the
   * client discards conflicting_memory_id and cannot recover from the conflict.
   */
  pathConflict: (message: string, conflictingPath: string, conflictingMemoryId?: string) =>
    respond(409, "memory_path_conflict_error", message, {
      conflicting_path: conflictingPath,
      ...(conflictingMemoryId ? { conflicting_memory_id: conflictingMemoryId } : {}),
    }),

  /**
   * 409 precondition failure.
   *
   * Never emit this when the supplied content_sha256 equals the stored content_sha256 —
   * the client treats a second conflict on unchanged content as repeated_spurious_conflict
   * and surfaces a hard error to the user. See memories.ts for the guard.
   */
  preconditionFailed: (message = MSG.PRECONDITION_FAILED) =>
    respond(409, "memory_precondition_failed_error", message),

  rateLimited: (message = "rate limit exceeded") => respond(429, "rate_limit_error", message),

  internal: (message = "internal error") => respond(500, "api_error", message),
};

/** Success responses on this surface are plain JSON with no envelope. */
export function ok(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
