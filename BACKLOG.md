# recall Improvement Backlog

Each iteration: pick top unclaimed item → smallest scoped change → pytest green → commit.
Revert immediately if tests go red. Tick the item done before moving on.

## Priority Queue

### P0 — Portability / OSS Hygiene
- [x] `lib/knowledge.py` `PROJECT_BUCKET_MAP` hardcodes user-specific paths (`-Users-exampleuser-...`). Move to an external config file `~/.claude/recall-buckets.json` with fallback to defaults. Keep backwards-compat: auto-migrate existing map if present.

### P1 — Test Coverage (zero coverage today)
- [x] Tests for `lib/knowledge.py` — cover `get_bucket_for_project`, `add_pending_learning`, `approve_learning`, `reject_learning`, `approve_all_pending`, `get_all_knowledge`, `get_knowledge_by_bucket`, `format_knowledge_summary`, `format_bucketed_summary`
- [x] Tests for `hooks/scripts/bash-failure.py` — cover failure categorization, SOP loading, pattern matching
- [x] Tests for `hooks/scripts/session-end.py` — cover `parse_session_full`, `extract_topics`, `build_summary`, `detect_learnings`
- [x] Tests for `bin/recall-sessions.py` — cover `search_sessions`, `format_session_list`, `format_session_detail`, `show_failures`
- [x] Tests for `bin/extract-knowledge.py` — cover `categorize_for_learning`, `extract_failure_resolution_pairs`, `extract_repeated_failure_patterns`
- [x] Tests for `bin/recall-restart.py` — cover `get_ticket_ids`, `get_theme`, `union_find_groups`, `find_child_projects`
- [x] Fix `extract-knowledge.py` NameError: `DEFAULT_BUCKET` imported but used before import (runtime crash on 3+ repeated failures)
- [x] Fix `recall-learn.py` regression: hardcoded bucket group list from pre-P0 (was `['business', 'tech', 'claude']`)
- [x] Replace all bare `except:` clauses with specific exception types (`OSError`, `IOError`, `ValueError`, etc.)

### P2 — Code Quality
- [x] `session-end.py` topic extraction: `TOPIC_STOP_WORDS` is a flat set — consider using a more efficient trie or at minimum document why this approach was chosen
- [x] `recall-sessions.py` is 1016 lines — split display/formatting functions to `lib/recall_format.py`
- [x] `get_project_folder()` in `shared.py` conflates path normalization and worktree resolution — extract `_normalize_path(cwd)` as a pure function for easier testing
- [x] `session-end.py`: `find_current_session` duplicates `_find_sessions_in_folder` logic — consolidate

### P3 — Features / UX
- [x] `PROJECT_BUCKET_MAP` migration script: auto-detect projects from `~/.claude/projects/` dir and suggest bucket assignments
- [x] `recall-sessions.py cleanup` command: currently shows analysis but doesn't act — add `--dry-run` and `--execute` flags
- [x] Session search: support multi-term AND queries (currently single-term only)
- [x] Add `--json` output flag to `recall-sessions.py` for programmatic use

### P4 — Test Coverage Round 2
- [x] Tests for `hooks/scripts/codex_session_end.py` — cover `parse_codex_rollout`, `categorize_error`, `create_session_summary`, `prune_index`
- [x] Tests for `bin/recall-learn.py` — cover `format_learning`, `show_pending` display, `approve_one`, `reject_one`
- [x] Tests for new `--json` flag in `recall-sessions.py` (list, search, failures)
- [x] Tests for `migrations/setup-buckets.py` — cover discovery, merge with existing config, dry-run
- [x] Tests for `lib/recall_format.py` standalone (currently covered via recall-sessions.py re-exports but not directly)

## Log
- 2026-04-24 ~iteration1: P0 — move PROJECT_BUCKET_MAP to ~/.claude/recall-buckets.json (e0fe677)
- 2026-04-24 ~iteration2: P1 — 31 tests for lib/knowledge.py (67f7b65)
- 2026-04-24 ~iteration3: P1 — 31 tests for bash-failure.py + sops.py (d17d84e)
- 2026-04-24 ~iteration4: P1 — 34 tests for session-end.py (5d5139a)
- 2026-04-24 ~iteration5: P1 — 26 tests for recall-sessions.py (2887fa6)
- 2026-04-24 ~iteration6: P3 — multi-term AND search in /recall (a366f12)
- 2026-04-24 ~iteration7: fix — bare except → specific types; recall-learn buckets; extract-knowledge DEFAULT_BUCKET (855a25b)
- 2026-04-24 ~iteration8: P1 — 21 tests for extract-knowledge.py (93c06f7)
- 2026-04-24 ~iteration9: P1 — 17 tests for recall-restart.py (272907b)
- 2026-04-24 ~iteration10: P2 — document TOPIC_STOP_WORDS set choice (4d24e1f)
- 2026-04-24 ~iteration11: P2 — extract _normalize_path() pure function (e9a733e)
- 2026-04-24 ~iteration12: P2 — consolidate JSONL glob+sort into _find_sessions_in_folder (7d3dd3e)
- 2026-04-24 ~iteration13: P2 — split 4 display fns to lib/recall_format.py; 1016→847 lines (945dc3e)
- 2026-04-24 ~iteration14: P3 — add --dry-run/--execute flags to cleanup command (73f7d88)
- 2026-04-24 ~iteration15: P3 — add --json output flag for programmatic use (fcb2359)
- 2026-04-24 ~iteration16: P3 — add setup-buckets.py migration helper (3778d30)
- 2026-04-24 ~iteration17: P4 — 38 tests for codex_session_end.py (dcb0b14)
- 2026-04-24 ~iteration18: P4 — 18 tests for recall-learn.py (b6752a5)
- 2026-04-24 ~iteration19: P4 — 13 tests for --json flag + setup-buckets.py (ecf3bdb)
- 2026-04-24 ~iteration20: P4 — 15 standalone tests for lib/recall_format.py (e75b53b)
- 2026-04-24 ~iteration21: P4 — 8 tests for _normalize_path/_resolve_cwd in shared.py (e7f6d42)
- 2026-04-24 ~iteration22: P4 — 8 tests for cmd_save in recall-restart.py (865d3a9)
- 2026-04-24 ~iteration23: P4 — 7 tests for cmd_match and cmd_launch (e16a18e)
- 2026-04-24 ~iteration24: P4 — 9 tests for find_current_session/cleanup_old_jsonl (249f298)
- 2026-04-24 ~iteration25: P4 — 7 tests for find_session_files/cleanup_jsonl_files (bae87e6)
- 2026-04-24 ~iteration26: P4 — 3 tests for list_all_project_indices (bc5a3a1)
- 2026-04-24 ~iteration27: P4 — 14 tests for lib/shared.py I/O functions (44256a6)
- 2026-04-24 ~iteration28: P4 — 3 tests for batch_approve in recall-learn.py (509aaeb)
- 2026-04-24 ~iteration29: P4 — 3 tests for find_latest_codex_session (9fde18f)
- 2026-04-24 ~iteration30: P4 — 3 tests for save_session_details in session-end.py (3d2d7fc)
- 2026-04-24 ~iteration31: P4 — test parent-directory grouping in union_find_groups (acbc08c)
- 2026-04-24 ~iteration32: P4 — 5 tests for search_sessions in recall-sessions.py (23d6895)
- 2026-04-24 ~iteration33: P4 — 3 tests for list_sessions in recall-sessions.py (c98fd43)
- 2026-04-24 ~iteration34: P4 — 4 tests for show_last_session in recall-sessions.py (f8bd862)
- 2026-04-24 ~iteration35: P4 — 3 tests for load_index/save_index wrappers in session-end.py (7ce1cc2)
- 2026-04-24 ~iteration36: P4 — 3 tests for reset_index in recall-sessions.py (58d2cdf)
- 2026-04-24 ~iteration37: P4 — 4 tests for cmd_list in recall-restart.py (2bbb8e8)
- 2026-04-24 ~iteration38: P4 — 7 tests for show_cleanup_analysis dispatch (e7a0999)
- 2026-04-24 ~iteration39: P4 — 5 tests for knowledge.py get_* functions (2d4cb58)
- 2026-04-24 ~iteration40: P4 — 2 tests for get_restarts_dir; 100% public fn coverage (e09ed4d)
- 2026-04-24 ~iteration41: P4 — 3 tests for import_index edge cases (5b42e27)
- 2026-04-24 ~iteration42: P4 — test sensitive cleanup via detail file content (3ba8176)
- 2026-04-24 ~iteration43: refactor — deduplicate categorize_error into lib/shared.py (ceee8e8)
- 2026-04-24 ~iteration44: P5 — 4 tests for untested parse_session_full branches (afc88c3)
- 2026-04-24 ~iteration45: P5 — 3 tests for untested search_sessions detail branches (14a431b)
- 2026-04-24 ~iteration46: P5 — 2 tests for show_pending unknown-bucket and recall-hint branches (08fd615)
- 2026-04-24 ~iteration47: P5 — test prune_stale_worktrees with unparseable timestamp (ca8b741)
- 2026-04-24 ~iteration48: P5 — test approve_learning with missing learnings key in old index (fb8ec09)
- 2026-04-24 ~iteration49: P5 — 2 tests for show_failures learning examples and non-dict paths (df6b146)
- 2026-04-24 ~iteration50: P5 — 2 tests for export_index empty-index and relative-path branches (76da765)
- 2026-04-24 ~iteration51: P5 — 2 tests for show_cleanup_analysis empty-index and noise-truncation (090364d)
- 2026-04-24 ~iteration52: P5 — test list_sessions JSONL fallback path (4389322)
- 2026-04-24 ~iteration53: P5 — 2 tests for sync_hooks auto_sync=False and strict secret scan (528afb3)
- 2026-04-24 ~iteration54: P5 — 2 tests for CloudProvider rate-limit and status error branches (da81ea2)
- 2026-04-24 ~iteration55: P5 — test gather_sync_files with secret_scan='off' (de12331)
- 2026-04-24 ~iteration56: P5 — 4 tests for sync_config corrupt YAML, missing key, and provider detection (90176cc)
- 2026-04-24 ~iteration57: P5 — 2 tests for sync_filename format and truncation (14c3b44)
- 2026-04-24 ~iteration58: P5 — 2 tests for scan_file IOError and private key detection (f99c255)
- 2026-04-24 ~iteration59: P5 — 2 tests for GitProvider status and init no-op (7cca2ff)
- 2026-04-24 ~iteration60: P5 — 2 tests for GitProvider push no-files and exception branches (17629d8)
- 2026-04-24 ~iteration61: P5 — 2 tests for CloudProvider push 507 and pull list-failure branches (7c8da2c)
- 2026-04-24 ~iteration62: P5 — 2 tests for maybe_sync_push no-files and maybe_sync_pull happy path (426f9c0)
- 2026-04-24 ~iteration63: P5 — test get_provider raises ValueError for unknown provider (274ca09)
- 2026-04-24 ~iteration64: P5 — 7 tests for session_start_helpers collect_todays_sessions and format_session_picker (1ae3726)
- 2026-04-24 ~iteration65: P5 — test format_sop with good-only example (no bad branch) (530667a)
- 2026-04-24 ~iteration66: P5 — test show_stats skips non-dict learnings in unused-learnings section (1767f63)
- 2026-04-24 ~iteration67: P5 — test load_agents returns [] when file contains dict not list (65e1100)
- 2026-04-24 ~iteration68: P5 — test keyword-based failure detection when exit code is zero (c086b87)
- 2026-04-24 ~iteration69: P5 — test outer IO exception handler stores error in parse_session_full result (841d4ff)
- 2026-04-24 ~iteration70: P5 — test export_index generates default timestamped filename when no path given (1bfcb1b)
- 2026-04-24 ~iteration71: P5 — test search_sessions finds match in skills_used field (0be9d35)
- 2026-04-24 ~iteration72: P5 — 2 tests for show_last_session: no-previous message and JSONL fallback path (1ab5da7)
- 2026-04-24 ~iteration73: P5 — test get_all_knowledge skips non-dict learnings (15455ee)
- 2026-04-24 ~iteration74: P5 — 2 tests for show_failures tools section and missing usage key creation (2a46b33)
- 2026-04-24 ~iteration75: P5 — test show_failures when failure has no error field (3eea4d2)
- 2026-04-24 ~iteration76: P5 — 2 tests for maybe_sync_pull manual mode skip and text content write (271eb2a)
- 2026-04-24 ~iteration77: P5 — 2 tests for show_cleanup_analysis sensitive sessions and duplicate count (6f438f3)
- 2026-04-24 ~iteration78: P5 — test list_sessions truncates long JSONL messages with ellipsis (290a404)
- 2026-04-24 ~iteration79: P5 — test read_state returns None when timestamp key is missing (0a97246)
- 2026-04-24 ~iteration80: P5 — 2 tests for _project_short_name filesystem-resolve and fallback paths (a535ca9)
- 2026-04-24 ~iteration81: P5 — test tolerates corrupt project sops.json file (5540526)
- 2026-04-24 ~iteration82: P5 — test summary appends second short message when summary < 120 chars (cfeb62f)
- 2026-04-24 ~iteration83: P5 — 2 tests for cross-project search no-other-projects and match-found branches (4b44fff)
- 2026-04-24 ~iteration84: P5 — 2 tests for extract-knowledge main() corrupt-stdin and no-project-folder branches (4cbed36)
- 2026-04-24 ~iteration85: P5 — test corrupt exec_command arguments gracefully skipped in codex parser (8f3a572)
- 2026-04-24 ~iteration86: P5 — test non-numeric RESTART_LEAD env var is ignored in cmd_save (6e98295)
- 2026-04-24 ~iteration87: P5 — test _launch_entry CalledProcessError falls back gracefully (b729a17)
- 2026-04-24 ~iteration88: P5 — test cleanup_jsonl_files prints no-old-files message when nothing freed (5cb57df)
- 2026-04-24 ~iteration89: P5 — test setup-buckets prints no-changes-needed when all projects already mapped (3d1694c)
- 2026-04-24 ~iteration90: P5 — test show_stats displays learnings_shown counts when non-empty (a9d49ee)
- 2026-04-24 ~iteration91: P5 — test cloud push records generic HTTP error and continues to next file (2549e4a)
- 2026-04-24 ~iteration92: P5 — test cloud pull skips files where individual GET returns non-200 (722d053)
- 2026-04-24 ~iteration93: P5 — test load_sync_config returns None when YAML file is empty (cbdcd27)
- 2026-04-24 ~iteration94: P5 — test show_failures with learnings and no failure patterns does not show empty message (6a7c7a6)
- 2026-04-24 ~iteration95: P5 — test show_failures increments existing learning display count (c0f6290)
- 2026-04-24 ~iteration96: P5 — test format_date converts non-string non-datetime via str() (b9ac507)
- 2026-04-24 ~iteration97: P5 — test cloud push captures per-file error when _http_request raises exception (1c40c6c)
- 2026-04-24 ~iteration98: P5 — 2 tests for maybe_sync_push/pull exception branches (68555f4)
- 2026-04-24 ~iteration99: P5 — test show_cleanup_analysis jsonl action dispatch (2ab4be7)
- 2026-04-24 ~iteration100: P5 — test parse_session outer IO exception stores error in result (0ddc5d1)
- 2026-04-24 ~iteration101: P5 — test cmd_match silently swallows IOError on unreadable prompt file (9dc7e0b)
- 2026-04-24 ~iteration102: P5 — test _launch_entry uses absolute prompt_file when relative candidate missing (16060a1)
- 2026-04-24 ~iteration103: P5 — 3 tests for update_worktree_registry new/existing project and no-branch branches (da24e36)
- 2026-04-24 ~iteration104: P5 — test resolve_worktree_root returns None on TimeoutExpired (3e62f75)
- 2026-04-24 ~iteration105: P5 — 2 tests for _load_worktree_registry corrupt JSON and non-dict content branches (251edcf)
- 2026-04-24 ~iteration106: P5 — test show_failures adds learnings_shown when usage exists but lacks the key (992e617)
- 2026-04-24 ~iteration107: P5 — test update_worktree_registry updates branch on existing worktree (c770dff)
- 2026-04-24 ~iteration108: P5 — test prune_stale_worktrees handles naive datetime (tzinfo is None) (642a18b)
- 2026-04-24 ~iteration109: P5 — test load_index returns empty index on corrupt file with create_if_missing=True (c06428c)
- 2026-04-24 ~iteration110: P5 — test _push_to_remote fallback and double-failure error append in GitProvider (0696a5b)
- 2026-04-24 ~iteration111: P5 — test _push_to_remote uses main fallback when current branch is master (15f6369)
- 2026-04-24 ~iteration112: P5 — test bitbucket provider detection branch in _detect_provider (ee7f4dd)
- 2026-04-24 ~iteration113: P5 — test pending_learnings key creation for legacy index in add_pending_learning (024b788)
- 2026-04-24 ~iteration114: P5 — test learnings key creation for legacy index in approve_all_pending (03cbdd3)
- 2026-04-24 ~iteration115: P5 — test non-directory entries skipped in collect_todays_sessions (cbe4974)
- 2026-04-24 ~iteration116: P5 — test empty-sessions branch in collect_todays_sessions (c4d0cb8)
- 2026-04-24 ~iteration117: P5 — test existing timestamp file read as since in maybe_sync_pull (e500985)
- 2026-04-24 ~iteration118: P5 — test failure-patterns header in search_sessions when no session match precedes (975f8f5)
- 2026-04-24 ~iteration119: P5 — test main() no-index branches for stats, export, import commands (6f6cf6b)
- 2026-04-24 ~iteration120: P5 — test failures no-index branch in main() dispatch (d38a179)
- 2026-04-24 ~iteration121: P5 — test learn-script-not-found branch in main() dispatch (20f1d30)
- 2026-04-24 ~iteration122: P5 — test No-user-messages-found fallback in list_sessions JSONL path (cfd4148)
- 2026-04-24 ~iteration123: P5 — test no-dash project name in cross-project search display (4bc0e11)
- 2026-04-24 ~iteration124: P5 — test worker entries launched after lead in cmd_launch (f2b1684)
- 2026-04-24 ~iteration125: P5 — test team env var included in _launch_entry command (21bbb5a)
- 2026-04-24 ~iteration126: P5 — test short-date else branch in sync_filename (3d74c5b)
- 2026-04-24 ~iteration127: P5 — test OSError swallow in cleanup_jsonl_files stat loop (d631d1f)
- 2026-04-24 ~iteration128: P5 — test relative path resolution branch in import_index (f445969)
- 2026-04-24 ~iteration129: P5 — test GitProvider default local_dir when None (97029ca)
- 2026-04-24 ~iteration130: P5 — test GitProvider.pull skips dotfiles (9a5337b)
- 2026-04-24 ~iteration131: P5 — test GitProvider.init fallback when clone fails (06e3196)
- 2026-04-24 ~iteration132: P5 — test load_sync_config uses default path when no arg given (3be83a5)
- 2026-04-24 ~iteration133: P5 — test push error-count log when provider returns partial failure (576944a)
- 2026-04-24 ~iteration134: P5 — test extract-knowledge main() happy path with repeated failures (36f69f1)
- 2026-04-24 ~iteration135: P5 — test 'and N more' branch in cross-project search (1af552c)
- 2026-04-24 ~iteration136: P5 — test learn cmd_arg passed to subprocess when script exists (b06618d)
- 2026-04-24 ~iteration137: P5 — test save_index derives project_folder when None (e019e37)
- 2026-04-24 ~iteration138: P5 — test get_project_dir derives folder when project_folder is None (8613883)
- 2026-04-24 ~iteration139: P5 — test collect_todays_sessions default projects_dir when None (6baa335)

## Done
<!-- move items here as they complete -->
