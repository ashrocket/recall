// Identifier generation and content hashing.
//
// ID shapes follow the Anthropic memory-stores surface so a client written against the
// documented API accepts our responses unchanged:
//   memstore_<26 base32>   mem_<26 base32>   memver_<26 base32>
//
// The client validates conflicting_memory_id against /^mem_[A-Za-z0-9]+$/, so the
// alphabet must stay alphanumeric — no hyphens, no underscores after the prefix.

const B32 = "abcdefghijklmnopqrstuvwxyz234567";

function randomBase32(length: number): string {
  const bytes = new Uint8Array(length);
  crypto.getRandomValues(bytes);
  let out = "";
  for (let i = 0; i < length; i++) out += B32[bytes[i] & 31];
  return out;
}

export const newStoreId = () => "memstore_" + randomBase32(26);
export const newMemoryId = () => "mem_" + randomBase32(26);
export const newVersionId = () => "memver_" + randomBase32(26);
export const newProjectId = () => "proj_" + randomHex(12);

function randomHex(byteLength: number): string {
  const bytes = new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  return [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export async function sha256Hex(input: string | ArrayBuffer): Promise<string> {
  const data = typeof input === "string" ? new TextEncoder().encode(input) : input;
  const digest = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function utf8Length(s: string): number {
  return new TextEncoder().encode(s).length;
}

/** RFC3339 UTC, second precision — the format every timestamp column stores. */
export function now(): string {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
}

/** R2 key for a memory blob. Content-addressed, so identical content dedupes. */
export function blobKey(storeId: string, sha256: string): string {
  return `mem/${storeId}/${sha256}`;
}
