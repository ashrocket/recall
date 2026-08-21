import type { Env } from "../index";

/** The worker Env plus the D1 binding the memory routes need. */
export interface MemoryEnv extends Env {
  DB: D1Database;
}

/**
 * Who is making the change. Recorded on every memory version so the audit trail
 * survives after the memory itself is gone.
 */
export interface Actor {
  userId: string;
  type: "api_actor" | "session_actor" | "user_actor" | "service_account_actor";
  id: string;
}
