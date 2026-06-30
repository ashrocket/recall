use serde_json::Value;
use std::collections::HashMap;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

fn main() {
    let cwd = env::args()
        .nth(1)
        .or_else(|| env::var("CLAUDE_PROJECT_DIR").ok())
        .or_else(|| {
            env::current_dir()
                .ok()
                .map(|p| p.to_string_lossy().to_string())
        })
        .unwrap_or_else(|| ".".to_string());

    let project_folder = get_project_folder(&cwd);
    let Some(index) = load_index(&project_folder) else {
        std::process::exit(64);
    };
    let Some(sessions) = index.get("sessions").and_then(Value::as_object) else {
        std::process::exit(64);
    };
    if sessions.is_empty() {
        std::process::exit(64);
    }

    let mut sorted_sessions: Vec<_> = sessions.iter().collect();
    sorted_sessions.sort_by(|a, b| value_str(b.1, "date").cmp(&value_str(a.1, "date")));
    if sorted_sessions.is_empty() {
        std::process::exit(64);
    }

    let output = if env_truthy("RECALL_SESSION_START_VERBOSE") {
        format_verbose_context(&index, &sorted_sessions)
    } else {
        format_compact_context(&index, &sorted_sessions)
    };

    println!("{}", output);
}

fn format_compact_context(index: &Value, sorted_sessions: &[(&String, &Value)]) -> String {
    let (_last_id, last_session) = sorted_sessions[0];
    let time_ago = format_time_ago(&value_str(last_session, "date"));
    let total_sessions = index
        .get("sessions")
        .and_then(Value::as_object)
        .map(|s| s.len())
        .unwrap_or(sorted_sessions.len());
    let pending = index
        .get("pending_learnings")
        .and_then(Value::as_array)
        .map(|a| a.len())
        .unwrap_or(0);
    let issue_count = significant_failure_patterns(index).len();

    let mut parts = vec![
        format!(
            "{} {} indexed",
            total_sessions,
            plural(total_sessions, "session", "sessions")
        ),
        format!("last {}", time_ago),
    ];
    if pending > 0 {
        parts.push(format!(
            "{} pending {}",
            pending,
            plural(pending, "learning", "learnings")
        ));
    }
    if issue_count > 0 {
        parts.push(format!(
            "{} recurring {} available",
            issue_count,
            plural(issue_count, "issue", "issues")
        ));
    }

    let mut detail_commands = vec!["/recall last"];
    if pending > 0 {
        detail_commands.push("/recall learn");
    }
    if issue_count > 0 {
        detail_commands.push("/recall failures");
    }

    format!(
        "Recall: {}. Details: {}.",
        parts.join("; "),
        detail_commands.join(" | ")
    )
}

fn format_verbose_context(index: &Value, sorted_sessions: &[(&String, &Value)]) -> String {
    let sessions = index
        .get("sessions")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();
    let mut output = Vec::new();
    output.push("## Session Context from /recall".to_string());
    output.push(String::new());

    let (_last_id, last_session) = sorted_sessions[0];
    let time_ago = format_time_ago(&value_str(last_session, "date"));
    output.push(format!(
        "**Last session** ({}): {}",
        time_ago,
        truncate(&value_str(last_session, "summary"), 150)
    ));

    let total_sessions = sessions.len();
    let total_failures: i64 = sessions
        .values()
        .map(|s| value_i64(s, "failure_count"))
        .sum();
    if total_sessions > 1 {
        output.push(format!(
            "**History**: {} sessions, {} total failures",
            total_sessions, total_failures
        ));
    }

    let knowledge_summary = format_knowledge_summary(&index);
    if !knowledge_summary.is_empty() {
        output.push(String::new());
        output.push("**Knowledge loaded:**".to_string());
        output.push(knowledge_summary);
    }

    let pending = index
        .get("pending_learnings")
        .and_then(Value::as_array)
        .map(|a| a.len())
        .unwrap_or(0);
    if pending > 0 {
        output.push(String::new());
        output.push(format!(
            "**Pending:** {} learnings awaiting review (`/recall learn`)",
            pending
        ));
    }

    let significant = significant_failure_patterns(&index);
    if !significant.is_empty() {
        output.push(String::new());
        output.push("**Recurring issues** (use `/recall failures` for details):".to_string());
        for (pattern, count, command) in significant.into_iter().take(3) {
            output.push(format!(
                "  - {}: {}x (last: `{}...`)",
                title_case(&pattern.replace('_', " ")),
                count,
                truncate(&command, 50)
            ));
        }
    }

    if let Some(messages) = last_session.get("user_messages").and_then(Value::as_array) {
        if let Some(last_msg) = messages
            .last()
            .and_then(|m| m.get("content").or(Some(m)))
            .and_then(Value::as_str)
        {
            let lower = last_msg.to_ascii_lowercase();
            if ["todo", "next", "later", "continue", "finish"]
                .iter()
                .any(|word| lower.contains(word))
            {
                output.push(String::new());
                output.push(format!(
                    "**Possible continuation**: \"{}...\"",
                    truncate(last_msg, 100)
                ));
            }
        }
    }

    output.push(String::new());
    output.push(
        "_Use `/recall` to search past sessions, `/recall last` for full previous session_"
            .to_string(),
    );
    output.push(String::new());

    output.join("\n")
}

fn plural<'a>(count: usize, singular: &'a str, plural: &'a str) -> &'a str {
    if count == 1 {
        singular
    } else {
        plural
    }
}

fn env_truthy(name: &str) -> bool {
    env::var(name)
        .map(|value| {
            matches!(
                value.trim().to_ascii_lowercase().as_str(),
                "1" | "true" | "yes" | "on" | "full" | "verbose"
            )
        })
        .unwrap_or(false)
}

fn home_dir() -> PathBuf {
    env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
}

fn project_dir(project_folder: &str) -> PathBuf {
    home_dir()
        .join(".claude")
        .join("projects")
        .join(project_folder)
}

fn load_index(project_folder: &str) -> Option<Value> {
    let path = project_dir(project_folder).join("recall-index.json");
    let data = fs::read_to_string(path).ok()?;
    serde_json::from_str(&data).ok()
}

fn get_project_folder(cwd: &str) -> String {
    let resolved = resolve_worktree_root(cwd).unwrap_or_else(|| cwd.to_string());
    resolved.replace('/', "-")
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

fn value_str(value: &Value, key: &str) -> String {
    value
        .get(key)
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string()
}

fn value_i64(value: &Value, key: &str) -> i64 {
    value.get(key).and_then(Value::as_i64).unwrap_or(0)
}

fn truncate(text: &str, max_chars: usize) -> String {
    text.chars().take(max_chars).collect()
}

fn significant_failure_patterns(index: &Value) -> Vec<(String, usize, String)> {
    let mut out = Vec::new();
    let Some(patterns) = index.get("failure_patterns").and_then(Value::as_object) else {
        return out;
    };
    for (pattern, failures) in patterns {
        let Some(items) = failures.as_array() else {
            continue;
        };
        if items.len() < 2 {
            continue;
        }
        let command = items
            .last()
            .and_then(|f| f.get("command"))
            .and_then(Value::as_str)
            .unwrap_or("unknown")
            .to_string();
        out.push((pattern.to_string(), items.len(), command));
    }
    out.sort_by_key(|(_, count, _)| std::cmp::Reverse(*count));
    out
}

fn format_knowledge_summary(index: &Value) -> String {
    let Some(learnings) = index.get("learnings").and_then(Value::as_array) else {
        return String::new();
    };
    if learnings.is_empty() {
        return String::new();
    }

    let mut buckets: HashMap<String, HashMap<String, usize>> = HashMap::new();
    for learning in learnings {
        let bucket = learning
            .get("bucket")
            .and_then(Value::as_str)
            .unwrap_or("personal")
            .to_string();
        let cat = learning
            .get("category")
            .and_then(Value::as_str)
            .unwrap_or("general")
            .to_string();
        *buckets.entry(bucket).or_default().entry(cat).or_default() += 1;
    }

    let mut bucket_keys: Vec<_> = buckets.keys().cloned().collect();
    bucket_keys.sort();
    let mut lines = Vec::new();
    for bucket in bucket_keys {
        let cats = &buckets[&bucket];
        let total: usize = cats.values().sum();
        let mut cat_names: Vec<_> = cats.keys().cloned().collect();
        cat_names.sort();
        lines.push(format!(
            "  **{}**: {} learnings ({})",
            title_case(&bucket),
            total,
            cat_names.join(", ")
        ));
    }
    lines.join("\n")
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

fn format_time_ago(date: &str) -> String {
    let Some(ts) = parse_iso_local_seconds(date) else {
        return truncate(date, 10);
    };
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(ts);
    let diff = now.saturating_sub(ts);
    let days = diff / 86_400;
    if days > 0 {
        format!("{}d ago", days)
    } else if diff > 3_600 {
        format!("{}h ago", diff / 3_600)
    } else if diff > 60 {
        format!("{}m ago", diff / 60)
    } else {
        "just now".to_string()
    }
}

fn parse_iso_local_seconds(date: &str) -> Option<i64> {
    if date.len() < 10 {
        return None;
    }
    let y: i64 = date.get(0..4)?.parse().ok()?;
    let m: i64 = date.get(5..7)?.parse().ok()?;
    let d: i64 = date.get(8..10)?.parse().ok()?;
    let hh: i64 = date.get(11..13).and_then(|s| s.parse().ok()).unwrap_or(0);
    let mm: i64 = date.get(14..16).and_then(|s| s.parse().ok()).unwrap_or(0);
    let ss: i64 = date.get(17..19).and_then(|s| s.parse().ok()).unwrap_or(0);
    Some(days_from_civil(y, m, d) * 86_400 + hh * 3_600 + mm * 60 + ss)
}

fn days_from_civil(mut y: i64, m: i64, d: i64) -> i64 {
    y -= if m <= 2 { 1 } else { 0 };
    let era = if y >= 0 { y } else { y - 399 } / 400;
    let yoe = y - era * 400;
    let mp = m + if m > 2 { -3 } else { 9 };
    let doy = (153 * mp + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146097 + doe - 719468
}
