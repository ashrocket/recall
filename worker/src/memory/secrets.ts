// Server-side secret scanning for memory content.
//
// recall already scans client-side in native_memory.plan() via sync_scan.scan_for_secrets.
// These are the same eight patterns, ported, so that a compromised or third-party client
// cannot write a credential into a store. Memories are replayed verbatim into every later
// session that reads the store, so a key written once leaks repeatedly.
//
// Keep this list in sync with lib/sync_scan.py.

const SECRET_PATTERNS: [string, RegExp][] = [
  ["AWS access key", /AKIA[0-9A-Z]{16}/i],
  ["API token (sk-)", /sk-[a-zA-Z0-9_-]{20,}/i],
  ["GitHub token", /ghp_[a-zA-Z0-9]{20,}/i],
  ["GitLab token", /glpat-[a-zA-Z0-9_-]{20,}/i],
  ["Bearer token", /Bearer\s+[a-zA-Z0-9._-]{20,}/i],
  ["Connection string", /(?:postgres|mongodb|mysql|redis):\/\/[^\s]+:[^\s]+@/i],
  ["Password field", /(?:password|passwd|secret)\s*[=:]\s*\S{8,}/i],
  ["Private key", /-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----/i],
];

export interface SecretFinding {
  type: string;
  line: number;
}

/** Returns the first finding, or null. Line-by-line so anchors behave per line. */
export function scanForSecret(content: string): SecretFinding | null {
  const lines = content.split("\n");
  for (let i = 0; i < lines.length; i++) {
    for (const [type, re] of SECRET_PATTERNS) {
      if (re.test(lines[i])) return { type, line: i + 1 };
    }
  }
  return null;
}
