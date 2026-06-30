use regex::Regex;
use serde_json::{json, Map, Value};
use std::cmp::Ordering;
use std::collections::{HashMap, HashSet};
use std::env;
use std::fs::{self, File};
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};

const SEARCH_SCAN_LIMIT: usize = 40;
const SEARCH_RESULT_LIMIT: usize = 8;
const SEARCH_SNIPPET_LIMIT: usize = 180;

#[derive(Clone, Debug)]
struct SearchResult {
    project: String,
    id: String,
    date: String,
    summary: String,
    source: String,
    text: String,
    snippet: String,
    message_count: i64,
    failure_count: i64,
    score: f64,
}

#[derive(Clone, Debug)]
struct ParsedSession {
    file: String,
    date: String,
    user_messages: Vec<String>,
    matches: Vec<String>,
}

fn main() {
    let raw_args: Vec<String> = env::args().skip(1).collect();
    if raw_args.is_empty() {
        eprintln!("Usage: recall-sessions.py <project_path> [search_term|last|failures]");
        std::process::exit(1);
    }

    let cwd = raw_args[0].clone();
    let json_mode = raw_args.iter().skip(1).any(|arg| arg == "--json");
    let command_args: Vec<String> = raw_args
        .iter()
        .skip(1)
        .filter(|arg| arg.as_str() != "--json")
        .cloned()
        .collect();
    let command = if command_args.is_empty() {
        None
    } else {
        Some(command_args.join(" "))
    };

    if let Some(command) = command.as_deref() {
        let cmd_name = command
            .split_whitespace()
            .next()
            .unwrap_or("")
            .to_ascii_lowercase();
        if matches!(cmd_name.as_str(), "help" | "--help" | "-h") {
            if json_mode {
                println!(
                    "{}",
                    json!({"commands": [
                        "list", "last", "search", "save", "restart", "learn",
                        "failures", "stats", "knowledge", "cleanup", "help"
                    ]})
                );
            } else {
                show_help();
            }
            return;
        }
    }

    let project_folder = get_project_folder(&cwd);
    let index = load_index(&project_folder);

    if index.is_none() {
        let sessions = find_session_files(&project_folder);
        if sessions.is_empty() {
            println!("No sessions found for project: {}", cwd);
            println!("Looking in: ~/.claude/projects/{}", project_folder);
            return;
        }
    }

    match command.as_deref() {
        None => {
            if json_mode {
                if let Some(index) = index.as_ref() {
                    output_session_list_json(index, &project_folder);
                } else {
                    println!("{}", json!({"project": project_folder, "sessions": []}));
                }
            } else {
                list_sessions(index.as_ref(), &project_folder);
            }
        }
        Some(command) => {
            let mut split = command.splitn(2, char::is_whitespace);
            let cmd_name = split.next().unwrap_or("").to_ascii_lowercase();
            let cmd_arg = split.next().map(str::trim).filter(|s| !s.is_empty());
            match cmd_name.as_str() {
                "list" => {
                    if json_mode {
                        if let Some(index) = index.as_ref() {
                            output_session_list_json(index, &project_folder);
                        } else {
                            println!("{}", json!({"project": project_folder, "sessions": []}));
                        }
                    } else {
                        list_sessions(index.as_ref(), &project_folder);
                    }
                }
                "last" => show_last_session(index.as_ref(), &project_folder),
                "failures" => {
                    if let Some(index) = index.as_ref() {
                        if json_mode {
                            println!(
                                "{}",
                                json!({
                                    "project": project_folder,
                                    "failure_patterns": index.get("failure_patterns").cloned().unwrap_or_else(|| json!({})),
                                    "learnings": index.get("learnings").cloned().unwrap_or_else(|| json!([])),
                                })
                            );
                        } else {
                            show_failures(index, &project_folder);
                        }
                    } else {
                        println!(
                            "No index available. Run a session to completion to build the index."
                        );
                    }
                }
                "stats" => {
                    if let Some(index) = index.as_ref() {
                        show_stats(index);
                    } else {
                        println!(
                            "No index available. Run a session to completion to build the index."
                        );
                    }
                }
                // Mutating and low-frequency commands stay on the Python implementation.
                "export" | "import" | "reset" | "cleanup" | "learn" | "knowledge" => {
                    eprintln!("unsupported-fast-command:{}", cmd_name);
                    std::process::exit(64);
                }
                _ => {
                    if json_mode {
                        let matches = index
                            .as_ref()
                            .map(|idx| {
                                collect_search_results(
                                    command,
                                    idx,
                                    &project_folder,
                                    SEARCH_SCAN_LIMIT,
                                    SEARCH_RESULT_LIMIT,
                                )
                            })
                            .unwrap_or_default();
                        println!(
                            "{}",
                            json!({
                                "search_term": command,
                                "matches": results_to_json(matches),
                            })
                        );
                    } else {
                        search_sessions(command, index.as_ref(), &project_folder);
                    }
                }
            }
            let _ = cmd_arg;
        }
    }
}

fn home_dir() -> PathBuf {
    env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
}

fn normalize_path(cwd: &str) -> String {
    cwd.replace('/', "-")
}

fn resolve_worktree_root(cwd: &str) -> Option<String> {
    let git_path = Path::new(cwd).join(".git");
    if git_path.is_file() {
        if let Ok(content) = fs::read_to_string(git_path) {
            let content = content.trim();
            if let Some(gitdir) = content.strip_prefix("gitdir:") {
                let gitdir = gitdir.trim();
                if let Some(idx) = gitdir.find("/.git/worktrees/") {
                    return Some(gitdir[..idx].to_string());
                }
            }
        }
    }

    for marker in ["/.worktrees/", "/.claude-worktrees/"] {
        if let Some(idx) = cwd.find(marker) {
            let parent = &cwd[..idx];
            if Path::new(parent).is_dir() {
                return Some(parent.to_string());
            }
        }
    }

    None
}

fn get_project_folder(cwd: &str) -> String {
    let resolved = resolve_worktree_root(cwd).unwrap_or_else(|| cwd.to_string());
    normalize_path(&resolved)
}

fn project_dir(project_folder: &str) -> PathBuf {
    home_dir()
        .join(".claude")
        .join("projects")
        .join(project_folder)
}

fn index_path(project_folder: &str) -> PathBuf {
    project_dir(project_folder).join("recall-index.json")
}

fn details_path(project_folder: &str, session_id: &str) -> PathBuf {
    project_dir(project_folder)
        .join("recall-sessions")
        .join(format!("{}.json", session_id))
}

fn load_index(project_folder: &str) -> Option<Value> {
    load_json(&index_path(project_folder))
}

fn load_json(path: &Path) -> Option<Value> {
    let data = fs::read_to_string(path).ok()?;
    serde_json::from_str(&data).ok()
}

fn sessions_map(index: &Value) -> Option<&Map<String, Value>> {
    index.get("sessions")?.as_object()
}

fn sorted_sessions(index: &Value) -> Vec<(&String, &Value)> {
    let mut sessions: Vec<_> = sessions_map(index)
        .map(|m| m.iter().collect())
        .unwrap_or_default();
    sessions.sort_by(|a, b| value_str(b.1, "date").cmp(&value_str(a.1, "date")));
    sessions
}

fn find_session_files(project_folder: &str) -> Vec<PathBuf> {
    let dir = project_dir(project_folder);
    let mut files = Vec::new();
    if let Ok(entries) = fs::read_dir(dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.extension().and_then(|s| s.to_str()) == Some("jsonl") {
                if !path
                    .file_name()
                    .and_then(|s| s.to_str())
                    .unwrap_or("")
                    .starts_with("agent-")
                {
                    files.push(path);
                }
            }
        }
    }
    files.sort_by(|a, b| {
        let am = a.metadata().and_then(|m| m.modified()).ok();
        let bm = b.metadata().and_then(|m| m.modified()).ok();
        bm.cmp(&am)
    });
    files
}

fn value_str<'a>(value: &'a Value, key: &str) -> String {
    value
        .get(key)
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string()
}

fn value_i64(value: &Value, key: &str) -> i64 {
    value.get(key).and_then(Value::as_i64).unwrap_or(0)
}

fn format_date(date: &str) -> String {
    if date.len() >= 16 {
        date[..16].replace('T', " ")
    } else {
        date.to_string()
    }
}

fn clip(text: &str, limit: usize) -> String {
    let compact = text.split_whitespace().collect::<Vec<_>>().join(" ");
    if compact.chars().count() <= limit {
        return compact;
    }
    let mut out = compact
        .chars()
        .take(limit.saturating_sub(1))
        .collect::<String>();
    out = out.trim_end().to_string();
    out.push('…');
    out
}

fn list_sessions(index: Option<&Value>, project_folder: &str) {
    println!("## Recent Sessions");
    println!();

    if let Some(index) = index {
        let sessions = sorted_sessions(index);
        if !sessions.is_empty() {
            for (i, (_session_id, session)) in sessions.into_iter().take(7).enumerate() {
                let current = if i == 0 { " (current)" } else { "" };
                let date = format_date(&value_str(session, "date"));
                let summary = clip(&value_str(session, "summary"), 150);
                let stats = format!(
                    "[{} msgs, {} fails]",
                    value_i64(session, "message_count"),
                    value_i64(session, "failure_count")
                );
                println!("**{}**{} {}", date, current, stats);
                println!("  {}", summary);
                println!();
            }
            return;
        }
    }

    for (i, session) in find_session_files(project_folder)
        .into_iter()
        .take(7)
        .enumerate()
    {
        let current = if i == 0 { " (current)" } else { "" };
        let data = parse_session(&session, None);
        let summary = data
            .user_messages
            .iter()
            .find(|msg| msg.chars().count() > 20)
            .map(|msg| clip(msg, 150))
            .unwrap_or_else(|| "No user messages found".to_string());
        println!("**{}**{}", format_date(&data.date), current);
        println!("  {}", summary);
        println!();
    }
}

fn file_mtime_seconds(path: &Path) -> String {
    path.metadata()
        .and_then(|m| m.modified())
        .ok()
        .and_then(|mtime| mtime.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|d| d.as_secs().to_string())
        .unwrap_or_else(|| "unknown".to_string())
}

fn parse_session(path: &Path, search_term: Option<&str>) -> ParsedSession {
    let mut parsed = ParsedSession {
        file: path
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("session")
            .to_string(),
        date: file_mtime_seconds(path),
        user_messages: Vec::new(),
        matches: Vec::new(),
    };

    let Ok(file) = File::open(path) else {
        return parsed;
    };
    for line in BufReader::new(file).lines().map_while(Result::ok) {
        let Ok(obj) = serde_json::from_str::<Value>(&line) else {
            continue;
        };
        if obj.get("type").and_then(Value::as_str) != Some("user") {
            continue;
        }
        let content = obj
            .get("message")
            .and_then(|m| m.get("content"))
            .and_then(Value::as_str)
            .unwrap_or("");
        if content.is_empty() || content.starts_with('<') {
            continue;
        }
        parsed.user_messages.push(clip(content, 500));
        if let Some(term) = search_term {
            if matches_search_query(content, term) {
                parsed.matches.push(clip(content, 300));
            }
        }
    }

    parsed
}

fn output_session_list_json(index: &Value, project_folder: &str) {
    let sessions: Vec<Value> = sorted_sessions(index)
        .into_iter()
        .map(|(sid, session)| {
            json!({
                "id": sid,
                "date": value_str(session, "date"),
                "summary": value_str(session, "summary"),
                "message_count": value_i64(session, "message_count"),
                "failure_count": value_i64(session, "failure_count"),
                "topics": session.get("topics").cloned().unwrap_or_else(|| json!([])),
            })
        })
        .collect();
    println!(
        "{}",
        json!({"project": project_folder, "sessions": sessions})
    );
}

fn show_last_session(index: Option<&Value>, project_folder: &str) {
    if let Some(index) = index {
        let sessions = sorted_sessions(index);
        if sessions.len() >= 2 {
            let (session_id, session_summary) = sessions[1];
            let details = load_json(&details_path(project_folder, session_id));
            println!("## Previous Session");
            println!(
                "**Date:** {}",
                format_date(&value_str(session_summary, "date"))
            );
            println!(
                "**Session:** {}...",
                &session_id.chars().take(8).collect::<String>()
            );
            println!(
                "**Stats:** {} messages, {} commands, {} failures",
                value_i64(session_summary, "message_count"),
                value_i64(session_summary, "command_count"),
                value_i64(session_summary, "failure_count")
            );
            println!();

            if let Some(details) = details {
                println!("### User Messages:");
                if let Some(messages) = details.get("user_messages").and_then(Value::as_array) {
                    for (i, msg) in messages.iter().take(15).enumerate() {
                        let content = if let Some(obj) = msg.as_object() {
                            obj.get("content").and_then(Value::as_str).unwrap_or("")
                        } else {
                            msg.as_str().unwrap_or("")
                        };
                        let clean = clip(&content.replace('\n', " "), 200);
                        if !clean.is_empty() {
                            println!("{}. {}", i + 1, clean);
                        }
                    }
                }
                if let Some(failures) = details.get("failures").and_then(Value::as_array) {
                    if !failures.is_empty() {
                        println!();
                        println!("### Failures:");
                        for failure in failures.iter().take(5) {
                            let cmd = clip(
                                failure.get("command").and_then(Value::as_str).unwrap_or(""),
                                80,
                            );
                            let error = clip(
                                failure.get("error").and_then(Value::as_str).unwrap_or(""),
                                150,
                            );
                            println!("  - `{}`", cmd);
                            println!("    {}", error);
                        }
                    }
                }
            } else {
                println!("### Summary:");
                println!("  {}", value_str(session_summary, "summary"));
                println!();
                println!(
                    "_(Full details not available - session was indexed before tiered storage)_"
                );
            }
            return;
        }
    }

    println!("No previous session found (only current session exists)");
}

fn normalize_search_query(query: &str) -> String {
    let mut normalized = query.split_whitespace().collect::<Vec<_>>().join(" ");
    if normalized.len() >= 2 {
        let first = normalized.chars().next().unwrap_or('\0');
        let last = normalized.chars().last().unwrap_or('\0');
        if first == last && matches!(first, '\'' | '"') {
            normalized = normalized[1..normalized.len() - 1].trim().to_string();
        }
    }
    normalized
}

fn literal_search_terms(query: &str) -> Vec<String> {
    normalize_search_query(query)
        .to_ascii_lowercase()
        .split_whitespace()
        .filter_map(|raw| {
            let term = raw
                .trim_matches(['\'', '"', '`'])
                .trim_matches(['?', '!', ',', ';', ':']);
            if term.is_empty() {
                None
            } else {
                Some(term.to_string())
            }
        })
        .collect()
}

fn compile_regex_query(query: &str) -> Result<Option<Regex>, String> {
    let normalized = normalize_search_query(query);
    if !normalized.starts_with('/') {
        return Ok(None);
    }
    let Some(closing) = normalized.rfind('/') else {
        return Ok(None);
    };
    if closing == 0 {
        return Ok(None);
    }
    let flags_text = &normalized[closing + 1..];
    if !flags_text.is_empty() && flags_text != "i" {
        return Ok(None);
    }
    if closing != normalized.len() - 1 && flags_text != "i" {
        return Ok(None);
    }
    let mut pattern = normalized[1..closing].to_string();
    if pattern.starts_with('*') {
        pattern.insert(0, '.');
    }
    let full = format!("(?i){}", pattern);
    Regex::new(&full).map(Some).map_err(|e| e.to_string())
}

fn matches_search_query(text: &str, query: &str) -> bool {
    match compile_regex_query(query) {
        Ok(Some(re)) => re.is_match(text),
        Ok(None) => {
            let lower = text.to_ascii_lowercase();
            literal_search_terms(query)
                .iter()
                .all(|term| lower.contains(term))
        }
        Err(_) => false,
    }
}

fn candidate_texts(details: &Value) -> Vec<(&'static str, String)> {
    let mut out = Vec::new();
    if let Some(messages) = details.get("user_messages").and_then(Value::as_array) {
        for msg in messages {
            let content = if let Some(obj) = msg.as_object() {
                obj.get("content").and_then(Value::as_str).unwrap_or("")
            } else {
                msg.as_str().unwrap_or("")
            };
            if !content.is_empty() {
                out.push(("msg", content.to_string()));
            }
        }
    }
    if let Some(commands) = details.get("commands").and_then(Value::as_array) {
        for cmd in commands {
            let text = cmd.get("command").and_then(Value::as_str).unwrap_or("");
            if !text.is_empty() {
                out.push(("cmd", text.to_string()));
            }
        }
    }
    if let Some(failures) = details.get("failures").and_then(Value::as_array) {
        for fail in failures {
            let command = fail.get("command").and_then(Value::as_str).unwrap_or("");
            let error = fail.get("error").and_then(Value::as_str).unwrap_or("");
            let text = format!("{} -> {}", command, error).trim().to_string();
            if !text.is_empty() && text != "->" {
                out.push(("fail", text));
            }
        }
    }
    if let Some(skills) = details.get("skills_used").and_then(Value::as_array) {
        for skill in skills {
            let name = skill.get("skill").and_then(Value::as_str).unwrap_or("");
            if !name.is_empty() {
                out.push(("skill", name.to_string()));
            }
        }
    }
    out
}

fn make_search_result(
    project: &str,
    session_id: &str,
    session_summary: &Value,
    source: &str,
    text: &str,
) -> SearchResult {
    let summary = value_str(session_summary, "summary");
    SearchResult {
        project: project.to_string(),
        id: session_id.to_string(),
        date: value_str(session_summary, "date"),
        summary,
        source: source.to_string(),
        text: text.to_string(),
        snippet: clip(text, SEARCH_SNIPPET_LIMIT),
        message_count: value_i64(session_summary, "message_count"),
        failure_count: value_i64(session_summary, "failure_count"),
        score: 1.0,
    }
}

fn collect_search_results(
    search_term: &str,
    index: &Value,
    project_folder: &str,
    session_limit: usize,
    result_limit: usize,
) -> Vec<SearchResult> {
    if compile_regex_query(search_term).is_err() {
        return Vec::new();
    }

    let mut candidates = Vec::new();
    for (session_id, session_summary) in sorted_sessions(index).into_iter().take(session_limit) {
        let summary = value_str(session_summary, "summary");
        if !summary.is_empty() && matches_search_query(&summary, search_term) {
            candidates.push(make_search_result(
                project_folder,
                session_id,
                session_summary,
                "summary",
                &summary,
            ));
        }
        if let Some(details) = load_json(&details_path(project_folder, session_id)) {
            for (source, text) in candidate_texts(&details) {
                if matches_search_query(&text, search_term) {
                    candidates.push(make_search_result(
                        project_folder,
                        session_id,
                        session_summary,
                        source,
                        &text,
                    ));
                }
            }
        }
    }

    if let Some(patterns) = index.get("failure_patterns").and_then(Value::as_object) {
        for (pattern, failures) in patterns {
            if let Some(failures) = failures.as_array() {
                for failure in failures {
                    let text = format!(
                        "{} {} -> {}",
                        pattern,
                        failure.get("command").and_then(Value::as_str).unwrap_or(""),
                        failure.get("error").and_then(Value::as_str).unwrap_or("")
                    );
                    if matches_search_query(&text, search_term) {
                        candidates.push(SearchResult {
                            project: project_folder.to_string(),
                            id: failure
                                .get("session_id")
                                .and_then(Value::as_str)
                                .unwrap_or("")
                                .to_string(),
                            date: failure
                                .get("date")
                                .and_then(Value::as_str)
                                .unwrap_or("")
                                .to_string(),
                            summary: pattern.to_string(),
                            source: "failure_pattern".to_string(),
                            text: text.clone(),
                            snippet: clip(&text, SEARCH_SNIPPET_LIMIT),
                            message_count: 0,
                            failure_count: failure
                                .get("count")
                                .and_then(Value::as_i64)
                                .unwrap_or(1),
                            score: 1.0,
                        });
                    }
                }
            }
        }
    }

    rank_search_results(search_term, candidates, result_limit)
}

fn tokenize(text: &str) -> Vec<String> {
    let stop_words: HashSet<&str> = [
        "about", "after", "again", "agent", "agents", "also", "and", "any", "are", "because",
        "been", "before", "being", "but", "can", "code", "codex", "context", "could", "current",
        "did", "does", "doing", "done", "every", "file", "files", "for", "from", "get", "git",
        "had", "has", "have", "here", "how", "into", "just", "like", "make", "more", "most",
        "need", "not", "now", "only", "out", "over", "please", "repo", "run", "same", "should",
        "some", "that", "the", "their", "them", "then", "there", "these", "this", "those",
        "through", "to", "try", "use", "used", "using", "was", "were", "what", "when", "where",
        "which", "while", "with", "work", "would", "you", "your",
    ]
    .into_iter()
    .collect();
    let mut out = Vec::new();
    let mut current = String::new();
    for ch in text.chars() {
        if ch.is_ascii_alphanumeric() || matches!(ch, '_' | '+' | '-') {
            current.push(ch.to_ascii_lowercase());
        } else if !current.is_empty() {
            let token = current.trim_matches(['_', '+', '-']).to_string();
            if token.len() >= 3
                && token
                    .chars()
                    .next()
                    .is_some_and(|c| c.is_ascii_alphabetic())
                && !stop_words.contains(token.as_str())
            {
                out.push(token);
            }
            current.clear();
        }
    }
    if !current.is_empty() {
        let token = current.trim_matches(['_', '+', '-']).to_string();
        if token.len() >= 3
            && token
                .chars()
                .next()
                .is_some_and(|c| c.is_ascii_alphabetic())
            && !stop_words.contains(token.as_str())
        {
            out.push(token);
        }
    }
    out
}

fn score_text(query: &str, text: &str) -> f64 {
    let query_tokens = tokenize(query);
    let text_tokens = tokenize(text);
    if query_tokens.is_empty() || text_tokens.is_empty() {
        return 0.0;
    }
    let mut query_counts: HashMap<&String, usize> = HashMap::new();
    for token in &query_tokens {
        *query_counts.entry(token).or_default() += 1;
    }
    let mut text_counts: HashMap<&String, usize> = HashMap::new();
    for token in &text_tokens {
        *text_counts.entry(token).or_default() += 1;
    }
    let action_terms: HashSet<&str> = [
        "add",
        "audit",
        "blocker",
        "build",
        "change",
        "check",
        "continue",
        "deploy",
        "edit",
        "error",
        "fail",
        "failure",
        "finish",
        "fix",
        "goal",
        "implement",
        "merge",
        "next",
        "open",
        "pending",
        "problem",
        "remove",
        "restart",
        "review",
        "save",
        "ship",
        "test",
        "update",
        "verify",
    ]
    .into_iter()
    .collect();

    let mut score = 0.0;
    let mut covered = 0.0;
    for (token, query_count) in query_counts {
        let mut text_count = *text_counts.get(token).unwrap_or(&0);
        if text_count == 0 {
            text_count = text_counts
                .iter()
                .filter(|(text_token, _)| text_token.contains(token.as_str()))
                .map(|(_, count)| *count)
                .sum();
        }
        if text_count > 0 {
            covered += 1.0;
            score += (1.0 + (text_count as f64).ln()) * (1.0 + (query_count as f64).ln());
            if action_terms.contains(token.as_str()) {
                score += 0.5;
            }
        }
    }
    let coverage = covered / (query_tokens.len() as f64);
    let density = score / (text_tokens.len() as f64).sqrt();
    density + (coverage * 2.0)
}

fn rank_search_results(
    search_term: &str,
    mut results: Vec<SearchResult>,
    limit: usize,
) -> Vec<SearchResult> {
    if results.is_empty() {
        return results;
    }
    for result in &mut results {
        let text = format!("{} {} {}", result.summary, result.source, result.text);
        result.score = score_text(search_term, &text);
        if result.score <= 0.0 {
            result.score = 1.0;
        }
    }
    results.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap_or(Ordering::Equal));
    results.truncate(limit);
    results
}

fn format_search_result(result: &SearchResult) -> String {
    match result.source.as_str() {
        "cmd" => format!("cmd: `{}`", clip(&result.text, SEARCH_SNIPPET_LIMIT)),
        "fail" => format!("fail: {}", clip(&result.text, SEARCH_SNIPPET_LIMIT)),
        "skill" => format!("skill: {}", result.snippet),
        "failure_pattern" => format!("Failure Patterns: {}", result.snippet),
        "summary" => format!("summary: {}", result.snippet),
        _ => format!("msg: {}", result.snippet),
    }
}

fn search_sessions(search_term: &str, index: Option<&Value>, project_folder: &str) {
    println!("## Top Matches: '{}'", search_term);
    println!();
    if let Err(err) = compile_regex_query(search_term) {
        println!("Invalid regex search: {}", err);
        println!(
            "Use slash-delimited regex like `/.*\\.p8/`, or quote a literal term like `'.p8'`."
        );
        return;
    }

    let local_results = index
        .map(|idx| {
            collect_search_results(
                search_term,
                idx,
                project_folder,
                SEARCH_SCAN_LIMIT,
                SEARCH_RESULT_LIMIT,
            )
        })
        .unwrap_or_default();
    if !local_results.is_empty() {
        for result in local_results {
            let short_id = result.id.chars().take(8).collect::<String>();
            let session = if short_id.is_empty() {
                String::new()
            } else {
                format!(" ({}...)", short_id)
            };
            println!(
                "### {}{} score={:.3}",
                format_date(&result.date),
                session,
                result.score
            );
            println!("  > {}", format_search_result(&result));
            println!();
        }
        return;
    }

    let mut found_raw = false;
    for session in find_session_files(project_folder).into_iter().take(10) {
        let data = parse_session(&session, Some(search_term));
        if data.matches.is_empty() {
            continue;
        }
        found_raw = true;
        let short_file = data.file.chars().take(8).collect::<String>();
        println!("### {} ({}...)", format_date(&data.date), short_file);
        for mat in data.matches.iter().take(3) {
            println!("  > {}...", clip(mat, 200));
        }
        println!();
    }
    if found_raw {
        return;
    }

    println!("No results in current project ({}).", project_folder);
    println!();

    let other_projects: Vec<String> = list_all_project_indices()
        .into_iter()
        .filter(|p| p != project_folder)
        .collect();
    if other_projects.is_empty() {
        println!("No other projects to search.");
        return;
    }

    let mut global_results: Vec<(String, Vec<SearchResult>)> = Vec::new();
    for project in other_projects {
        if let Some(project_index) = load_index(&project) {
            let matches =
                collect_search_results(search_term, &project_index, &project, SEARCH_SCAN_LIMIT, 5);
            if !matches.is_empty() {
                global_results.push((project, matches));
            }
        }
    }

    if global_results.is_empty() {
        println!("No matches found for '{}' in any project.", search_term);
        return;
    }

    println!(
        "Found matches in {} other project(s):",
        global_results.len()
    );
    println!();
    for (project, matches) in global_results {
        let proj_name = project.rsplit('-').next().unwrap_or(&project);
        println!("### {} ({} ranked matches)", proj_name, matches.len());
        for mat in matches.iter().take(3) {
            let date = mat.date.chars().take(10).collect::<String>();
            println!("  > [{}] {}", date, clip(&format_search_result(mat), 150));
        }
        if matches.len() > 3 {
            println!("  ... and {} more ranked matches", matches.len() - 3);
        }
        println!();
    }
}

fn list_all_project_indices() -> Vec<String> {
    let projects_dir = home_dir().join(".claude").join("projects");
    let mut projects = Vec::new();
    if let Ok(entries) = fs::read_dir(projects_dir) {
        for entry in entries.flatten() {
            if entry.path().is_dir() && entry.path().join("recall-index.json").exists() {
                if let Some(name) = entry.file_name().to_str() {
                    projects.push(name.to_string());
                }
            }
        }
    }
    projects
}

fn result_to_json(result: SearchResult) -> Value {
    json!({
        "project": result.project,
        "id": result.id,
        "date": result.date,
        "summary": result.summary,
        "source": result.source,
        "text": result.text,
        "snippet": result.snippet,
        "message_count": result.message_count,
        "failure_count": result.failure_count,
        "score": (result.score * 10000.0).round() / 10000.0,
    })
}

fn results_to_json(results: Vec<SearchResult>) -> Value {
    Value::Array(results.into_iter().map(result_to_json).collect())
}

fn show_failures(index: &Value, _project_folder: &str) {
    println!("## Failure Patterns Across Sessions");
    println!();

    let learnings = index.get("learnings").and_then(Value::as_array);
    if let Some(learnings) = learnings {
        if !learnings.is_empty() {
            println!("## Learnings & Best Practices");
            println!();
            for learning in learnings {
                if let Some(obj) = learning.as_object() {
                    let cat = obj
                        .get("category")
                        .and_then(Value::as_str)
                        .unwrap_or("general");
                    let title = obj
                        .get("title")
                        .and_then(Value::as_str)
                        .unwrap_or("Unknown");
                    println!("### [{}] {}", cat, title);
                    if let Some(desc) = obj.get("description").and_then(Value::as_str) {
                        if !desc.is_empty() {
                            println!("  {}", desc);
                        }
                    }
                    let fix = obj.get("fix").and_then(Value::as_str).unwrap_or("");
                    let solution = obj.get("solution").and_then(Value::as_str).unwrap_or("");
                    let guidance = if !fix.is_empty() { fix } else { solution };
                    if !guidance.is_empty() {
                        let first_line = guidance.lines().next().unwrap_or(guidance);
                        let suffix = if guidance.contains('\n') { "..." } else { "" };
                        println!("  **Fix:** {}{}", first_line, suffix);
                    }
                    println!();
                } else {
                    println!("  - {}", learning);
                }
            }
            println!();
        }
    }

    let Some(patterns) = index.get("failure_patterns").and_then(Value::as_object) else {
        if learnings.map(|l| l.is_empty()).unwrap_or(true) {
            println!("No failure patterns or learnings recorded yet.");
        }
        return;
    };
    if patterns.is_empty() {
        if learnings.map(|l| l.is_empty()).unwrap_or(true) {
            println!("No failure patterns or learnings recorded yet.");
        }
        return;
    }

    let mut sorted: Vec<_> = patterns.iter().collect();
    sorted.sort_by_key(|(_, failures)| {
        std::cmp::Reverse(failures.as_array().map(|a| a.len()).unwrap_or(0))
    });
    for (pattern, failures) in sorted {
        let items = failures.as_array().map(Vec::as_slice).unwrap_or(&[]);
        let pattern_name = pattern.replace('_', " ");
        println!(
            "### {} ({} occurrences)",
            title_case(&pattern_name),
            items.len()
        );
        println!();
        let start = items.len().saturating_sub(5);
        for failure in &items[start..] {
            let date = failure
                .get("date")
                .and_then(Value::as_str)
                .unwrap_or("unknown");
            let cmd = clip(
                failure
                    .get("command")
                    .and_then(Value::as_str)
                    .unwrap_or("unknown"),
                60,
            );
            let error = clip(
                failure.get("error").and_then(Value::as_str).unwrap_or(""),
                100,
            );
            println!(
                "  **{}**: `{}`",
                date.chars().take(10).collect::<String>(),
                cmd
            );
            if !error.is_empty() {
                println!("    Error: {}...", error);
            }
        }
        println!();
    }
}

fn title_case(text: &str) -> String {
    text.split_whitespace()
        .map(|word| {
            let mut chars = word.chars();
            match chars.next() {
                Some(first) => first.to_uppercase().collect::<String>() + chars.as_str(),
                None => String::new(),
            }
        })
        .collect::<Vec<_>>()
        .join(" ")
}

fn show_stats(index: &Value) {
    println!("## Recall Usage Statistics");
    println!();
    let usage = index.get("usage").and_then(Value::as_object);
    let skills = usage
        .and_then(|u| u.get("skills"))
        .and_then(Value::as_object);

    println!("### Skill Invocations");
    if let Some(skills) = skills {
        if !skills.is_empty() {
            println!();
            let mut sorted: Vec<_> = skills.iter().collect();
            sorted.sort_by_key(|(_, data)| {
                std::cmp::Reverse(data.get("count").and_then(Value::as_i64).unwrap_or(0))
            });
            for (skill_name, data) in sorted {
                let count = data.get("count").and_then(Value::as_i64).unwrap_or(0);
                let last = data
                    .get("last_used")
                    .and_then(Value::as_str)
                    .unwrap_or("never");
                let sessions = data
                    .get("sessions")
                    .and_then(Value::as_array)
                    .map(|a| a.len())
                    .unwrap_or(0);
                println!(
                    "  **{}**: {} uses across {} sessions (last: {})",
                    skill_name,
                    count,
                    sessions,
                    last.chars().take(10).collect::<String>()
                );
            }
            println!();
        } else {
            println!("  No skill usage tracked yet.");
            println!();
        }
    } else {
        println!("  No skill usage tracked yet.");
        println!();
    }

    let learnings_shown = usage
        .and_then(|u| u.get("learnings_shown"))
        .and_then(Value::as_object);
    println!("### Learnings Displayed");
    if let Some(learnings) = learnings_shown {
        if !learnings.is_empty() {
            println!();
            let mut sorted: Vec<_> = learnings.iter().collect();
            sorted.sort_by_key(|(_, data)| {
                std::cmp::Reverse(data.get("count").and_then(Value::as_i64).unwrap_or(0))
            });
            for (learning_key, data) in sorted {
                let count = data.get("count").and_then(Value::as_i64).unwrap_or(0);
                let last = data
                    .get("last_shown")
                    .and_then(Value::as_str)
                    .unwrap_or("never");
                println!(
                    "  **{}**: shown {} times (last: {})",
                    learning_key,
                    count,
                    last.chars().take(10).collect::<String>()
                );
            }
            println!();
        } else {
            println!("  No learning displays tracked yet.");
            println!();
        }
    } else {
        println!("  No learning displays tracked yet.");
        println!();
    }

    let total_skills: i64 = skills
        .map(|m| {
            m.values()
                .map(|v| v.get("count").and_then(Value::as_i64).unwrap_or(0))
                .sum()
        })
        .unwrap_or(0);
    let total_learnings: i64 = learnings_shown
        .map(|m| {
            m.values()
                .map(|v| v.get("count").and_then(Value::as_i64).unwrap_or(0))
                .sum()
        })
        .unwrap_or(0);
    println!("### Summary");
    println!("  Total skill invocations: {}", total_skills);
    println!("  Total learning displays: {}", total_learnings);
    println!(
        "  Unique skills used: {}",
        skills.map(|m| m.len()).unwrap_or(0)
    );
    println!(
        "  Unique learnings shown: {}",
        learnings_shown.map(|m| m.len()).unwrap_or(0)
    );
}

fn show_help() {
    println!("## /recall Help");
    println!();
    println!("`/recall` is one command with script-backed subcommands and search fallback.");
    println!();
    println!("### Core");
    println!("  `/recall`                    List recent sessions");
    println!("  `/recall list`               List recent sessions");
    println!("  `/recall last`               Show the previous session");
    println!("  `/recall <term>`             Search messages, commands, failures, skills");
    println!("  `/recall '.p8'`              Search for a literal token or filename fragment");
    println!("  `/recall /.*\\.p8/`           Regex search");
    println!("  `/recall /*\\.p8/`            Forgiving regex shorthand for the same search");
    println!();
    println!("### Workflow");
    println!("  `/recall save`               Save current work as a restart prompt");
    println!("  `/recall restart`            List saved restart prompts");
    println!("  `/recall restart <n|text>`   Load by list number, or match by text");
    println!("  `/recall restart --launch <n|text>`");
    println!("                              Open the restart in a separate window");
    println!("  `/recall learn`              Review pending learnings");
    println!("  `/recall failures`           Show failure patterns and approved learnings");
    println!();
    println!("### Maintenance");
    println!("  `/recall stats`              Show usage stats");
    println!("  `/recall knowledge`          Show loaded knowledge");
    println!("  `/recall cleanup`            Analyze cleanup opportunities");
    println!("  `/recall help`               Show this help");
}
