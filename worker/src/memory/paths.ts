// Memory path validation.
//
// The checks run in a fixed order and the FIRST failure wins, because which message the
// client receives determines which reason it reports and whether it retries. Reordering
// these changes client behaviour even though every branch still returns 400.

import { MSG, LIMITS } from "./errors";
import { utf8Length } from "./ids";

// Control and format characters that must never appear in a path: C0, C1, zero-width
// and bidi controls, and the invisible-formatting blocks.
const CONTROL_CHARS =
  /[\u0000-\u001f\u007f-\u009f\u200b-\u200f\u2028-\u202e\u2060-\u206f\ufeff]/;

/** Returns null when the path is valid, or the exact client-facing message when not. */
export function validatePath(path: string): string | null {
  if (!path.startsWith("/")) return MSG.PATH_LEADING_SLASH;
  if (utf8Length(path) > LIMITS.MAX_PATH_BYTES) return MSG.PATH_TOO_LONG;

  const segments = path.slice(1).split("/");
  if (segments.length > LIMITS.MAX_PATH_SEGMENTS) return MSG.PATH_TOO_DEEP;

  for (const seg of segments) {
    if (seg === "." || seg === "..") return MSG.PATH_DOT_SEGMENT;
  }
  for (const seg of segments) {
    if (seg === "") return MSG.PATH_EMPTY_SEGMENT;
  }

  if (CONTROL_CHARS.test(path)) return MSG.PATH_CONTROL_CHARS;
  if (path !== path.normalize("NFC")) return MSG.PATH_NOT_NFC;

  return null;
}

/**
 * The proper ancestor paths of `path` that end on a segment boundary, trailing slash
 * stripped. `/a/b/c.md` -> ["/a", "/a/b"].
 *
 * Used to detect the case where a document already occupies a prefix of a path we are
 * about to write — a file and a directory of the same name cannot coexist.
 */
export function ancestorPaths(path: string): string[] {
  const out: string[] = [];
  for (let i = 1; i < path.length; i++) {
    if (path[i] === "/") out.push(path.slice(0, i));
  }
  return out;
}

/**
 * Bounds for a descendant range scan: everything strictly under `path/`.
 *
 * '/' is 0x2f and '0' is 0x30, so [path + "/", path + "0") covers exactly the children
 * of `path` and nothing else.
 */
export function descendantRange(path: string): { lo: string; hi: string } {
  return { lo: path + "/", hi: path + "0" };
}

/** Normalisation the client applies before comparing conflicting_path to its request. */
export function normalizePath(path: string): string {
  return path.normalize("NFC");
}
