// native/src/capture.rs - Faithful port of capture.py hot paths (final fixed version)
use lazy_static::lazy_static;
use parking_lot::Mutex;
use pyo3::prelude::*;
use regex::Regex;
use rusqlite::{params, Connection};
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;

const DEFAULT_MAX_TEXT: usize = 4000;
const DEFAULT_MAX_FILES: usize = 100;
const DEFAULT_LEASE_SECONDS: i64 = 300;
const MAX_RETRY_DELAY_SECONDS: i64 = 300;
const DEFAULT_RETENTION_DAYS: i64 = 30;
const DEFAULT_MAX_META: usize = 2000;

const DEFAULT_SENSITIVE_PATHS: &[&str] = &[
    ".env", ".env.*", "*/.ssh/*", "*/.aws/*", "*.pem", "*.key",
    "*id_rsa*", "*id_ed25519*", "*.p12", "*.pfx",
];

const PROMPT_FIELDS: &[&str] = &["prompt", "submitted_prompt", "user_message"];
const ASSISTANT_FIELDS: &[&str] = &[
    "last_assistant_message", "prompt_response", "response", "final_response",
];
const HOST_META_FIELDS: &[&str] = &[
    "transcript_path", "model", "permission_mode", "client_type", "source",
    "reason", "trigger", "error_type", "error_message", "agent_type", "agent_id",
    "stop_hook_active", "turn_id", "session_title", "profile", "platform",
    "uptime_ms", "token_count", "estimated_token_count", "custom_instructions",
];

fn is_consolidation_event(event: &str) -> bool {
    matches!(event, "session-end" | "stop" | "stop-failure" | "interrupt" | "pre-compact" | "post-compaction")
}

lazy_static! {
    static ref EVENT_ALIASES: HashMap<&'static str, &'static str> = {
        let mut m = HashMap::new();
        m.insert("sessionstart", "session-start");
        m.insert("session-start", "session-start");
        m.insert("sessionend", "session-end");
        m.insert("session-end", "session-end");
        m.insert("userpromptsubmit", "user-prompt-submit");
        m.insert("user-prompt-submit", "user-prompt-submit");
        m.insert("user-prompt", "user-prompt-submit");
        m.insert("pretooluse", "pre-tool-use");
        m.insert("pre-tool-use", "pre-tool-use");
        m.insert("posttooluse", "post-tool-use");
        m.insert("post-tool-use", "post-tool-use");
        m.insert("posttoolusefailure", "post-tool-use-failure");
        m.insert("post-tool-use-failure", "post-tool-use-failure");
        m.insert("precompact", "pre-compact");
        m.insert("pre-compact", "pre-compact");
        m.insert("postcompaction", "post-compaction");
        m.insert("post-compaction", "post-compaction");
        m.insert("postcompact", "post-compaction");
        m.insert("post-compact", "post-compaction");
        m.insert("stop", "stop");
        m.insert("stopfailure", "stop-failure");
        m.insert("stop-failure", "stop-failure");
        m.insert("interrupt", "interrupt");
        m.insert("sessionheartbeat", "session-heartbeat");
        m.insert("session-heartbeat", "session-heartbeat");
        m.insert("subagentstop", "subagent-stop");
        m.insert("subagent-stop", "subagent-stop");
        m.insert("beforeagent", "user-prompt-submit");
        m.insert("before-agent", "user-prompt-submit");
        m.insert("afteragent", "stop");
        m.insert("after-agent", "stop");
        m.insert("beforetool", "pre-tool-use");
        m.insert("before-tool", "pre-tool-use");
        m.insert("aftertool", "post-tool-use");
        m.insert("after-tool", "post-tool-use");
        m.insert("precompress", "pre-compact");
        m.insert("pre-compress", "pre-compact");
        m.insert("pre-tool-call", "pre-tool-use");
        m.insert("post-tool-call", "post-tool-use");
        m.insert("on-session-start", "session-start");
        m.insert("on-session-end", "session-end");
        m.insert("pre-llm-call", "user-prompt-submit");
        m
    };

    static ref CLIENT_ALIASES: HashMap<&'static str, &'static str> = {
        let mut m = HashMap::new();
        m.insert("claude", "claude");
        m.insert("claude-code", "claude");
        m.insert("claude_code", "claude");
        m.insert("anthropic", "claude");
        m.insert("codex", "codex");
        m.insert("codex-cli", "codex");
        m.insert("openai", "codex");
        m.insert("gemini", "gemini");
        m.insert("gemini-cli", "gemini");
        m.insert("google", "gemini");
        m.insert("qwen", "qwen");
        m.insert("qwen-code", "qwen");
        m.insert("qwen_code", "qwen");
        m.insert("kimi", "kimi");
        m.insert("kimi-code", "kimi");
        m.insert("kimi_code_cli", "kimi");
        m.insert("kimi-cli", "kimi");
        m.insert("hermes", "hermes");
        m.insert("hermes-agent", "hermes");
        m.insert("cursor", "cursor");
        m.insert("chatgpt", "chatgpt");
        m.insert("user", "user");
        m.insert("other", "other");
        m
    };

    static ref CLIENT_PREFIX_INDEX: HashMap<char, &'static str> = {
        let mut index = HashMap::new();
        for key in CLIENT_ALIASES.keys() {
            if let Some(first) = key.chars().next() {
                index.entry(first).or_insert(*key);
            }
        }
        index
    };

    static ref SECRET_PATTERNS: Vec<(Regex, &'static str)> = vec![
        (Regex::new(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----").unwrap(), "private key"),
        (Regex::new(r"(?i)\b(?:api[_ -]?key|secret[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|passwd)\b\s*[=:]\s*\S+").unwrap(), "credential assignment"),
        (Regex::new(r"(?i)\bsk-[A-Za-z0-9_-]{16,}\b").unwrap(), "API-style secret"),
        (Regex::new(r"(?i)\bgh[pousr]_[A-Za-z0-9]{20,}\b").unwrap(), "GitHub token"),
        (Regex::new(r"(?i)\bAKIA[0-9A-Z]{16}\b").unwrap(), "AWS access key"),
        (Regex::new(r"(?i)\b(?:seed phrase|mnemonic)\b\s*[=:]\s*(?:[a-z]+\s+){7,}[a-z]+").unwrap(), "seed phrase"),
    ];
}

lazy_static! {
    static ref TO_KEBAB_RE_2: Regex = Regex::new(r"[^A-Za-z0-9_\-]+").unwrap();
    static ref TO_KEBAB_RE_3: Regex = Regex::new(r"-+").unwrap();
}

fn to_kebab(value: &str, limit: usize) -> String {
    // Faithful port of Python's to_kebab:
    // 1. Insert hyphen between lowercase/digit and uppercase (camelCase boundary)
    // 2. Replace underscores with hyphens
    // 3. Replace non-alphanumeric (except hyphens) with hyphens
    // 4. Collapse multiple hyphens
    // 5. Trim leading/trailing hyphens and lowercase
    
    // Step 1: Insert hyphen at camelCase boundaries
    // Python: TO_KEBAB_RE_1 = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
    let mut result = String::with_capacity(value.len());
    let chars: Vec<char> = value.chars().collect();
    for i in 0..chars.len() {
        if i > 0 {
            let prev = chars[i - 1];
            let curr = chars[i];
            if (prev.is_ascii_lowercase() || prev.is_ascii_digit()) && curr.is_ascii_uppercase() {
                result.push('-');
            }
        }
        result.push(chars[i]);
    }
    
    // Step 2: Replace underscores with hyphens
    let s = result.replace('_', "-");
    // Step 3: Replace non-alphanumeric (except hyphens) with hyphens
    let s = TO_KEBAB_RE_2.replace_all(&s, "-");
    // Step 4: Collapse multiple hyphens
    let s = TO_KEBAB_RE_3.replace_all(&s, "-");
    // Step 5: Trim leading/trailing hyphens and lowercase
    let s = s.trim_matches('-').to_lowercase();
    if s.len() > limit { s[..limit].to_string() } else { s }
}

fn truncated_text(value: Option<&str>, maximum: usize) -> String {
    match value {
        Some(v) => {
            let stripped = v.trim();
            if stripped.len() > maximum { stripped[..maximum].to_string() } else { stripped.to_string() }
        }
        None => String::new(),
    }
}

fn one_line(value: &str, limit: usize) -> String {
    let s: String = value.replace('\x00', " ").split_whitespace().collect::<Vec<_>>().join(" ");
    if s.len() > limit { s[..limit].to_string() } else { s }
}

fn utc_timestamp() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let duration = SystemTime::now().duration_since(UNIX_EPOCH).unwrap();
    let secs = duration.as_secs();
    let nanos = duration.subsec_nanos();
    let days = secs / 86400;
    let secs_of_day = secs % 86400;
    format!("{:04}-{:02}-{:02}T{:02}:{:02}:{:02}.{:09}Z",
        1970 + days / 365, (days % 365) / 30 + 1, (days % 365) % 30 + 1,
        secs_of_day / 3600, (secs_of_day % 3600) / 60, secs_of_day % 60, nanos)
}

#[pyfunction]
#[pyo3(signature = (value=None))]
pub fn normalize_event(value: Option<&str>) -> String {
    let raw = match value { Some(v) => v.trim(), None => "" };
    if raw.is_empty() { return "observation".to_string(); }
    let kebab = to_kebab(raw, 80);
    if let Some(&alias) = EVENT_ALIASES.get(kebab.as_str()) { return alias.to_string(); }
    let no_hyphens = kebab.replace("-", "");
    if let Some(&alias) = EVENT_ALIASES.get(no_hyphens.as_str()) { return alias.to_string(); }
    kebab
}

#[pyfunction]
#[pyo3(signature = (value=None))]
pub fn normalize_client(value: Option<&str>) -> String {
    let raw = match value {
        Some(v) => v.trim().to_lowercase().replace(" ", "-"),
        None => return String::new(),
    };
    if raw.is_empty() { return String::new(); }
    if let Some(&alias) = CLIENT_ALIASES.get(raw.as_str()) { return alias.to_string(); }
    if let Some(first_key) = CLIENT_PREFIX_INDEX.get(&raw.chars().next().unwrap_or('\0')) {
        for (key, writer) in CLIENT_ALIASES.iter() {
            if key.chars().next() == first_key.chars().next() && raw.starts_with(*key) {
                return writer.to_string();
            }
        }
    }
    if raw.len() > 100 { raw[..100].to_string() } else { raw }
}

fn capture_exclude_patterns() -> Vec<String> {
    let configured = std::env::var("MEMORY_CAPTURE_EXCLUDE_PATHS").unwrap_or_default();
    let custom: Vec<String> = configured.split(',')
        .map(|item| item.trim().replace('\\', "/").to_lowercase())
        .filter(|item| !item.is_empty())
        .collect();
    let mut result: Vec<String> = DEFAULT_SENSITIVE_PATHS.iter().map(|s| s.to_string()).collect();
    result.extend(custom);
    result
}

fn wildcard_match(text: &str, pattern: &str) -> bool {
    let mut ti = 0;
    let mut pi = 0;
    let tc: Vec<char> = text.chars().collect();
    let pc: Vec<char> = pattern.chars().collect();
    while ti < tc.len() && pi < pc.len() {
        match pc[pi] {
            '*' => {
                for start in ti..=tc.len() {
                    if wildcard_match(&text[start..], &pattern[pi + 1..]) { return true; }
                }
                return false;
            }
            '?' => { ti += 1; pi += 1; }
            c => {
                if tc[ti] == c { ti += 1; pi += 1; } else { return false; }
            }
        }
    }
    while pi < pc.len() && pc[pi] == '*' { pi += 1; }
    ti == tc.len() && pi == pc.len()
}

fn sensitive_path(value: &str) -> bool {
    let normalized = value.replace('\\', "/").to_lowercase();
    let name = normalized.rsplit('/').last().unwrap_or("");
    let patterns = capture_exclude_patterns();
    patterns.iter().any(|p| wildcard_match(&normalized, p) || wildcard_match(name, p))
}

fn check_text(text: &str) -> (bool, String) {
    let t = one_line(text, 1500);
    if t.is_empty() { return (false, "empty memory".to_string()); }
    if t.len() > 1500 { return (false, "memory is too long; store a durable compressed fact instead".to_string()); }
    for (pattern, label) in SECRET_PATTERNS.iter() {
        if pattern.is_match(&t) { return (false, format!("probable sensitive data detected: {}", label)); }
    }
    if looks_like_card(&t) { return (false, "probable sensitive data detected: possible payment/account number".to_string()); }
    let high_risk = Regex::new(r"(?i)\b(?:aadhaar|aadhar|pan number|passport number|bank account|routing number|cvv|pin code for account)\b").unwrap();
    if high_risk.is_match(&t) { return (false, "probable sensitive identifier".to_string()); }
    (true, String::new())
}

fn looks_like_card(text: &str) -> bool {
    let card_re = Regex::new(r"\b\d{4}(?:[ -]?\d{4}){2,3}(?:[ -]?\d{1,3})?\b").unwrap();
    for m in card_re.find_iter(text) {
        let digits: String = m.as_str().chars().filter(|c| c.is_ascii_digit()).collect();
        if (13..=19).contains(&digits.len()) && luhn_ok(&digits) { return true; }
    }
    false
}

fn luhn_ok(digits: &str) -> bool {
    let mut total = 0;
    for (i, ch) in digits.chars().rev().enumerate() {
        let mut d = ch.to_digit(10).unwrap_or(0);
        if i % 2 == 1 { d *= 2; if d > 9 { d -= 9; } }
        total += d;
    }
    total % 10 == 0
}

#[pyfunction]
#[pyo3(signature = (value=None, excluded_paths=vec![]))]
pub fn sanitize_text(value: Option<&str>, excluded_paths: Vec<String>) -> String {
    let mut text = truncated_text(value, DEFAULT_MAX_TEXT);
    for (pattern, _) in SECRET_PATTERNS.iter() {
        text = pattern.replace_all(&text, "[redacted sensitive evidence]").to_string();
    }
    for path in &excluded_paths {
        if !path.is_empty() { text = text.replace(path, "[redacted sensitive path]"); }
    }
    let result = check_text(&text);
    if !result.0 && result.1.contains("sensitive") {
        return "[redacted sensitive evidence]".to_string();
    }
    text
}

#[pyfunction]
pub fn sanitize_payload(payload: HashMap<String, String>) -> HashMap<String, String> {
    let sensitive_keys = [
        "input_summary", "output_summary", "prompt", "submitted_prompt",
        "user_message", "last_assistant_message", "prompt_response", "response",
        "final_response", "error_message", "reason", "trigger", "source",
    ];
    let mut sanitized = HashMap::new();
    for (key, value) in &payload {
        if sensitive_keys.contains(&key.as_str()) {
            sanitized.insert(key.clone(), sanitize_text(Some(value), Vec::new()));
        } else {
            sanitized.insert(key.clone(), value.clone());
        }
    }
    sanitized
}

#[pyclass]
#[derive(Clone)]
pub struct Observation {
    #[pyo3(get, set)]
    pub observation_id: String,
    #[pyo3(get, set)]
    pub session_id: String,
    #[pyo3(get, set)]
    pub project: String,
    #[pyo3(get, set)]
    pub cwd: String,
    #[pyo3(get, set)]
    pub tool: String,
    #[pyo3(get, set)]
    pub files: Vec<String>,
    #[pyo3(get, set)]
    pub input_summary: String,
    #[pyo3(get, set)]
    pub output_summary: String,
    #[pyo3(get, set)]
    pub git_commit: String,
    #[pyo3(get, set)]
    pub created_at: String,
    #[pyo3(get, set)]
    pub source: String,
    #[pyo3(get, set)]
    pub event: String,
    #[pyo3(get, set)]
    pub host_meta: HashMap<String, String>,
    #[pyo3(get, set)]
    pub worktree: String,
    #[pyo3(get, set)]
    pub project_source: String,
}

#[pymethods]
impl Observation {
    #[new]
    fn new() -> Self {
        Observation {
            observation_id: String::new(), session_id: String::new(),
            project: String::new(), cwd: String::new(), tool: String::new(),
            files: Vec::new(), input_summary: String::new(), output_summary: String::new(),
            git_commit: String::new(), created_at: String::new(), source: String::new(),
            event: String::new(), host_meta: HashMap::new(),
            worktree: String::new(), project_source: String::new(),
        }
    }

    fn __repr__(&self) -> String {
        format!("Observation(observation_id={}, session_id={}, event={})",
            self.observation_id, self.session_id, self.event)
    }
}

fn row_to_map(row: &rusqlite::Row<'_>) -> HashMap<String, String> {
    let mut map = HashMap::new();
    let count = row.as_ref().column_count();
    for i in 0..count {
        let name = row.as_ref().column_name(i).map(|s| s.to_string()).unwrap_or_default();
        let value: String = row.get::<_, Option<String>>(i).unwrap_or(None).unwrap_or_default();
        map.insert(name, value);
    }
    map
}

#[pyclass]
pub struct ObservationBuffer {
    conn: Arc<Mutex<Connection>>,
    retention_days: i64,
}

#[pymethods]
impl ObservationBuffer {
    #[new]
    #[pyo3(signature = (path=None))]
    fn new(path: Option<&str>) -> PyResult<Self> {
        let db_path = if let Some(p) = path {
            PathBuf::from(p)
        } else {
            let configured = std::env::var("MEMORY_CAPTURE_DB").unwrap_or_default();
            if !configured.is_empty() {
                PathBuf::from(configured)
            } else {
                let home = std::env::var("HOME").or_else(|_| std::env::var("USERPROFILE")).unwrap_or_default();
                PathBuf::from(home).join(".ai-memory-hub").join("observations.sqlite3")
            }
        };

        let retention_days = std::env::var("MEMORY_CAPTURE_RETENTION_DAYS")
            .ok().and_then(|s| s.parse().ok()).unwrap_or(DEFAULT_RETENTION_DAYS);
        let retention_days = retention_days.max(0);

        if let Some(parent) = db_path.parent() { std::fs::create_dir_all(parent).ok(); }

        let conn = Connection::open(&db_path).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyIOError, _>(format!("Failed to open DB: {}", e))
        })?;

        conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;").map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("PRAGMA failed: {}", e))
        })?;

        conn.execute(
            "CREATE TABLE IF NOT EXISTS observations (
                observation_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, project TEXT NOT NULL,
                cwd TEXT NOT NULL, tool TEXT NOT NULL, files_json TEXT NOT NULL,
                input_summary TEXT NOT NULL, output_summary TEXT NOT NULL,
                git_commit TEXT NOT NULL, created_at TEXT NOT NULL, source TEXT NOT NULL,
                event TEXT NOT NULL DEFAULT 'observation', status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, claim_token TEXT,
                lease_expires_at TEXT, next_attempt_at TEXT,
                host_meta_json TEXT NOT NULL DEFAULT '{}',
                worktree TEXT NOT NULL DEFAULT '', project_source TEXT NOT NULL DEFAULT ''
            )", []).map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("CREATE failed: {}", e)))?;

        let columns: Vec<String> = conn.prepare("PRAGMA table_info(observations)")
            .and_then(|mut stmt| {
                let rows = stmt.query_map([], |row| row.get::<_, String>(1))
                    .map_err(|e| e)?;
                Ok(rows.collect::<Result<Vec<String>, _>>()?)
            }).unwrap_or_default();

        for col in &["event", "claim_token", "lease_expires_at", "next_attempt_at", "host_meta_json", "worktree", "project_source"] {
            if !columns.contains(&col.to_string()) {
                let sql = match *col {
                    "event" => "ALTER TABLE observations ADD COLUMN event TEXT NOT NULL DEFAULT 'observation'",
                    "claim_token" => "ALTER TABLE observations ADD COLUMN claim_token TEXT",
                    "lease_expires_at" => "ALTER TABLE observations ADD COLUMN lease_expires_at TEXT",
                    "next_attempt_at" => "ALTER TABLE observations ADD COLUMN next_attempt_at TEXT",
                    "host_meta_json" => "ALTER TABLE observations ADD COLUMN host_meta_json TEXT NOT NULL DEFAULT '{}'",
                    "worktree" => "ALTER TABLE observations ADD COLUMN worktree TEXT NOT NULL DEFAULT ''",
                    "project_source" => "ALTER TABLE observations ADD COLUMN project_source TEXT NOT NULL DEFAULT ''",
                    _ => "",
                };
                if !sql.is_empty() { conn.execute(sql, []).ok(); }
            }
        }

        conn.execute("CREATE INDEX IF NOT EXISTS idx_observations_session ON observations(session_id, created_at)", []).ok();
        conn.execute("CREATE INDEX IF NOT EXISTS idx_observations_status ON observations(status, created_at)", []).ok();
        conn.execute("CREATE INDEX IF NOT EXISTS idx_observations_event ON observations(event, created_at)", []).ok();
        conn.execute("CREATE INDEX IF NOT EXISTS idx_observations_project ON observations(project, created_at)", []).ok();
        conn.execute("COMMIT", []).ok();

        Ok(ObservationBuffer { conn: Arc::new(Mutex::new(conn)), retention_days })
    }

    #[pyo3(signature = (include_pending=None))]
    fn prune_expired(&self, include_pending: Option<bool>) -> PyResult<usize> {
        if self.retention_days <= 0 { return Ok(0); }
        let include_pending = include_pending.unwrap_or(false);
        let cutoff = utc_timestamp();
        let statuses = if include_pending {
            vec!["pending", "failed", "processing", "completed"]
        } else { vec!["completed", "failed"] };

        let placeholders = statuses.iter().map(|_| "?").collect::<Vec<_>>().join(",");
        let sql = format!("DELETE FROM observations WHERE created_at < ? AND status IN ({})", placeholders);
        let conn = self.conn.lock();
        let mut stmt = conn.prepare(&sql).map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        let mut params: Vec<&dyn rusqlite::ToSql> = vec![&cutoff];
        for s in &statuses { params.push(s); }
        let affected = stmt.execute(&*params).map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(affected)
    }

    fn close(&self) {}

    fn append(&self, payload: &Observation) -> PyResult<HashMap<String, String>> {
        let mut conn = self.conn.lock();
        let tx = conn.transaction().map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Transaction failed: {}", e)))?;
        let files_json = serde_json::to_string(&payload.files).unwrap_or_default();
        let host_meta_json = serde_json::to_string(&payload.host_meta).unwrap_or_default();
        let result = tx.execute(
            "INSERT OR IGNORE INTO observations (observation_id, session_id, project, cwd, tool, files_json,
             input_summary, output_summary, git_commit, created_at, source, event, host_meta_json, worktree, project_source)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            params![&payload.observation_id, &payload.session_id, &payload.project, &payload.cwd,
                &payload.tool, &files_json, &payload.input_summary, &payload.output_summary,
                &payload.git_commit, &payload.created_at, &payload.source, &payload.event,
                &host_meta_json, &payload.worktree, &payload.project_source],
        );
        let duplicate = matches!(result, Ok(0));
        tx.commit().map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Commit failed: {}", e)))?;

        let mut result_map = HashMap::new();
        result_map.insert("observation_id".to_string(), payload.observation_id.clone());
        result_map.insert("session_id".to_string(), payload.session_id.clone());
        result_map.insert("project".to_string(), payload.project.clone());
        result_map.insert("cwd".to_string(), payload.cwd.clone());
        result_map.insert("tool".to_string(), payload.tool.clone());
        result_map.insert("input_summary".to_string(), payload.input_summary.clone());
        result_map.insert("output_summary".to_string(), payload.output_summary.clone());
        result_map.insert("git_commit".to_string(), payload.git_commit.clone());
        result_map.insert("created_at".to_string(), payload.created_at.clone());
        result_map.insert("source".to_string(), payload.source.clone());
        result_map.insert("event".to_string(), payload.event.clone());
        result_map.insert("duplicate".to_string(), duplicate.to_string());
        Ok(result_map)
    }

    #[pyo3(signature = (session_id, limit=None, statuses=None))]
    fn for_session(&self, session_id: &str, limit: Option<usize>, statuses: Option<Vec<String>>) -> PyResult<Vec<HashMap<String, String>>> {
        let limit = limit.unwrap_or(500).clamp(1, 5000);
        let mut params: Vec<String> = vec![session_id.to_string()];
        let mut where_clause = "session_id=?".to_string();
        if let Some(status_list) = statuses {
            let ph = status_list.iter().map(|_| "?").collect::<Vec<_>>().join(",");
            where_clause.push_str(&format!(" AND status IN ({})", ph));
            params.extend(status_list);
        }
        let sql = format!("SELECT * FROM observations WHERE {} ORDER BY created_at, observation_id LIMIT ?", where_clause);
        let conn = self.conn.lock();
        let mut stmt = conn.prepare(&sql).map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        let mut qp: Vec<&dyn rusqlite::ToSql> = Vec::new();
        for p in &params { qp.push(p); }
        qp.push(&limit);
        let rows = stmt.query_map(&*qp, |row| Ok(row_to_map(row)))
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        let mut results = Vec::new();
        for row in rows { results.push(row.map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?); }
        Ok(results)
    }

    #[pyo3(signature = (limit=None))]
    fn pending_sessions(&self, limit: Option<usize>) -> PyResult<Vec<String>> {
        let limit = limit.unwrap_or(100).clamp(1, 1000);
        let conn = self.conn.lock();
        let mut stmt = conn.prepare("SELECT DISTINCT session_id FROM observations WHERE status IN ('pending', 'failed', 'processing') ORDER BY session_id LIMIT ?")
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        let rows = stmt.query_map([limit], |row| row.get::<_, String>(0))
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        rows.collect::<Result<Vec<_>, _>>().map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
    }

    #[pyo3(signature = (rows, limit=None))]
    fn batch_sequence(&self, rows: Vec<HashMap<String, String>>, limit: Option<usize>) -> PyResult<i64> {
        let limit = limit.unwrap_or(500).clamp(1, 5000) as i64;
        if rows.is_empty() { return Ok(0); }
        let first = &rows[0];
        let session_id = first.get("session_id").map(|s| s.as_str()).unwrap_or("");
        let created_at = first.get("created_at").map(|s| s.as_str()).unwrap_or("");
        let observation_id = first.get("observation_id").map(|s| s.as_str()).unwrap_or("");
        let conn = self.conn.lock();
        let before: i64 = conn.query_row(
            "SELECT COUNT(*) FROM observations WHERE session_id=? AND (created_at < ? OR (created_at=? AND observation_id <= ?))",
            params![session_id, created_at, created_at, observation_id], |row| row.get(0)).unwrap_or(0);
        Ok(((before - 1) / limit) + 1)
    }

    fn recover_processing(&self, session_id: &str) -> PyResult<usize> {
        let now = utc_timestamp();
        let mut conn = self.conn.lock();
        let tx = conn.transaction().map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        let affected = tx.execute(
            "UPDATE observations SET status='failed', attempts=attempts+1, last_error=?, claim_token=NULL,
             lease_expires_at=NULL, next_attempt_at=? WHERE session_id=? AND status='processing'
             AND (lease_expires_at IS NULL OR lease_expires_at <= ?)",
            params!["recovered after interrupted consolidation", &now, session_id, &now],
        ).map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        tx.commit().map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        Ok(affected)
    }

    #[pyo3(signature = (session_id, owner, limit=None, lease_seconds=None))]
    fn claim_for_session(&self, session_id: &str, owner: &str, limit: Option<usize>, lease_seconds: Option<i64>) -> PyResult<Vec<HashMap<String, String>>> {
        let limit = limit.unwrap_or(500).clamp(1, 5000);
        let _lease_seconds = lease_seconds.unwrap_or(DEFAULT_LEASE_SECONDS).max(1);
        let now = utc_timestamp();
        let owner_owned = owner.to_string();

        let mut conn = self.conn.lock();
        let ids: Vec<String> = {
            let tx = conn.transaction().map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Transaction failed: {}", e)))?;
            let ids: Vec<String> = {
                let mut stmt = tx.prepare(
                    "SELECT observation_id FROM observations WHERE session_id=? AND status IN ('pending','failed')
                     AND (next_attempt_at IS NULL OR next_attempt_at <= ?) ORDER BY created_at, observation_id LIMIT ?"
                ).map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
                let ids: Vec<String> = stmt.query_map(params![session_id, &now, limit], |row| row.get::<_, String>(0))
                    .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?
                    .collect::<Result<Vec<_>, _>>().map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
                ids
            };
            tx.commit().map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
            ids
        };

        if ids.is_empty() { return Ok(Vec::new()); }

        let placeholders = ids.iter().map(|_| "?").collect::<Vec<_>>().join(",");
        let sql = format!(
            "UPDATE observations SET status='processing', attempts=attempts+1, claim_token=?, lease_expires_at=?,
             last_error=NULL, next_attempt_at=NULL WHERE observation_id IN ({}) AND status IN ('pending','failed') RETURNING *",
            placeholders
        );

        // Split into two transactions to avoid borrow issues
        let results: Vec<HashMap<String, String>> = {
            let tx = conn.transaction().map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Transaction failed: {}", e)))?;
            let mut query_params: Vec<Box<dyn rusqlite::ToSql>> = Vec::new();
            query_params.push(Box::new(owner_owned.clone()));
            query_params.push(Box::new(now.clone()));
            for id in &ids { query_params.push(Box::new(id.clone())); }
            
            let results = {
                let mut stmt = tx.prepare(&sql).map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
                let rows = stmt.query_map(rusqlite::params_from_iter(query_params.iter()), |row| Ok(row_to_map(row)))
                    .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
                rows.collect::<Result<Vec<_>, _>>().map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?
            };
            tx.commit().map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
            results
        };

        Ok(results)
    }

    #[pyo3(signature = (observation_ids, status, error=None, owner=None))]
    fn mark_status(&self, observation_ids: Vec<String>, status: &str, error: Option<&str>, owner: Option<&str>) -> PyResult<usize> {
        match status {
            "pending" | "processing" | "completed" | "failed" => {}
            _ => return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>("invalid observation status")),
        }
        if observation_ids.is_empty() { return Ok(0); }
        let owner_clause = if owner.is_some() { " AND claim_token=?" } else { "" };
        let bounded_error = error.map(|e| truncated_text(Some(e), 1000));

        let mut conn = self.conn.lock();
        let placeholders = observation_ids.iter().map(|_| "?").collect::<Vec<_>>().join(",");
        let sql = format!("SELECT observation_id, attempts, status FROM observations WHERE observation_id IN ({}){}", placeholders, owner_clause);

        let rows = {
            let tx = conn.transaction().map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
            let rows = {
                let mut stmt = tx.prepare(&sql).map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
                let mut query_params: Vec<Box<dyn rusqlite::ToSql>> = Vec::new();
                for id in &observation_ids { query_params.push(Box::new(id.clone())); }
                if let Some(o) = owner { query_params.push(Box::new(o.to_string())); }
                let rows = stmt.query_map(rusqlite::params_from_iter(query_params.iter()), |row| {
                    Ok((row.get::<_, String>(0)?, row.get::<_, i64>(1)?, row.get::<_, String>(2)?))
                }).map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
                rows.collect::<Result<Vec<_>, _>>().map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?
            };
            tx.commit().map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
            rows
        };

        if rows.is_empty() { return Ok(0); }

        let update_sql = format!("UPDATE observations SET status=?, attempts=?, last_error=?, claim_token=NULL,
            lease_expires_at=?, next_attempt_at=? WHERE observation_id=?{}", owner_clause);

        for (obs_id, attempts, prev_status) in &rows {
            let new_attempts = attempts + 1;
            let retry_at = if status == "failed" {
                let delay = if prev_status != "failed" {
                    0
                } else {
                    (2_i64.pow((*attempts as u32).min(8))).min(MAX_RETRY_DELAY_SECONDS)
                };
                if delay > 0 { Some(format!("{}s", delay)) } else { None }
            } else { None };

            let tx = conn.transaction().map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
            let mut update_params: Vec<Box<dyn rusqlite::ToSql>> = Vec::new();
            update_params.push(Box::new(status.to_string()));
            update_params.push(Box::new(new_attempts));
            update_params.push(Box::new(bounded_error.clone().unwrap_or_default()));
            update_params.push(Box::new(None::<String>));
            update_params.push(Box::new(retry_at));
            update_params.push(Box::new(obs_id.clone()));
            if let Some(o) = owner { update_params.push(Box::new(o.to_string())); }

            tx.execute(&update_sql, rusqlite::params_from_iter(update_params.iter()))
                .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
            tx.commit().map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        }

        Ok(rows.len())
    }

    #[pyo3(signature = (statuses=None))]
    fn pending_count(&self, statuses: Option<Vec<String>>) -> PyResult<usize> {
        let values = statuses.unwrap_or_else(|| vec!["pending".to_string(), "failed".to_string()]);
        let placeholders = values.iter().map(|_| "?").collect::<Vec<_>>().join(",");
        let sql = format!("SELECT COUNT(*) FROM observations WHERE status IN ({})", placeholders);
        let conn = self.conn.lock();
        let mut query_params: Vec<&dyn rusqlite::ToSql> = Vec::new();
        for v in &values { query_params.push(v); }
        let count: i64 = conn.query_row(&sql, &*query_params, |row| row.get(0)).unwrap_or(0);
        Ok(count as usize)
    }

    #[pyo3(signature = (project, statuses=None, limit=None))]
    fn sessions_for_project(&self, project: &str, statuses: Option<Vec<String>>, limit: Option<usize>) -> PyResult<Vec<String>> {
        let limit = limit.unwrap_or(100).clamp(1, 1000);
        let mut params: Vec<String> = vec![project.to_string()];
        let mut where_clause = "project=?".to_string();
        if let Some(status_list) = statuses {
            let ph = status_list.iter().map(|_| "?").collect::<Vec<_>>().join(",");
            where_clause.push_str(&format!(" AND status IN ({})", ph));
            params.extend(status_list);
        }
        let sql = format!("SELECT session_id, MAX(created_at) AS latest FROM observations WHERE {} GROUP BY session_id ORDER BY latest DESC LIMIT ?", where_clause);
        let conn = self.conn.lock();
        let mut stmt = conn.prepare(&sql).map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        let mut qp: Vec<&dyn rusqlite::ToSql> = Vec::new();
        for p in &params { qp.push(p); }
        qp.push(&limit);
        let rows = stmt.query_map(&*qp, |row| row.get::<_, String>(0))
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
        rows.collect::<Result<Vec<_>, _>>().map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
    }
}

#[pyfunction]
#[pyo3(signature = (path=None))]
pub fn create_observation_buffer(path: Option<&str>) -> PyResult<ObservationBuffer> {
    ObservationBuffer::new(path)
}
