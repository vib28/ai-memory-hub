// native/src/tokenization.rs - Faithful port of context_packet.py tokenization
use lazy_static::lazy_static;
use parking_lot::Mutex;
use pyo3::prelude::*;
use regex::Regex;
use std::collections::{HashMap, HashSet};
use std::sync::Arc;

// ---------------------------------------------------------------------------
// Constants (from context_packet.py lines 64-104)
// ---------------------------------------------------------------------------

lazy_static! {
    static ref WORD_RE: Regex = Regex::new(r"[a-z0-9][a-z0-9_\-\.]{2,}").unwrap();
}

// _MIN_CONTENT_TOKEN_LEN = 6 (line 104)
const MIN_CONTENT_TOKEN_LEN: usize = 6;

lazy_static! {
    static ref STOPWORDS: HashSet<&'static str> = {
        let mut s = HashSet::new();
        // Lines 65-96 of context_packet.py -- every entry faithfully ported
        for w in [
            "the", "and", "for", "with", "that", "this", "from", "into", "have", "what", "when",
            "your", "please", "make", "just", "like", "about", "then", "them", "they", "will",
            "should", "could", "would", "there", "their", "here", "also", "some", "more", "than",
            "very", "does", "done", "need", "want", "using", "use", "add", "fix", "can", "you",
            "are", "not", "but", "all", "any", "run", "running", "runs", "ran", "install",
            "installing", "installed", "installation", "check", "checking", "checked", "checks",
            "start", "started", "starting", "starts", "server", "servers", "client", "clients",
            "system", "systems", "setup", "setups", "configure", "configuring", "configured",
            "configuration", "get", "getting", "got", "gets", "let", "lets", "letting", "know",
            "knowing", "known", "knows", "likely", "unlike", "likes", "look", "looking", "looked",
            "looks", "find", "finding", "found", "finds", "tell", "telling", "told", "tells",
            "give", "giving", "given", "gives", "gave", "help", "helping", "helped", "helps",
            "show", "showing", "shown", "shows", "showed", "work", "working", "worked", "works",
            "call", "calling", "called", "calls", "try", "trying", "tried", "tries", "keep",
            "keeping", "kept", "keeps", "wanting", "wanted", "wants", "thing", "things",
            "something", "anything", "nothing", "way", "ways", "part", "parts", "good", "great",
            "well", "better", "best", "new", "old", "first", "last", "next", "one", "two",
            "three", "four", "five", "much", "many", "several", "few", "may", "might", "must",
            "still", "already", "even", "ever", "never", "back", "now", "today", "always",
            "really", "actually", "probably", "certainly", "quite", "rather", "enough", "almost",
        ] {
            s.insert(w);
        }
        s
    };
}

// ---------------------------------------------------------------------------
// _tokens() - faithful port of context_packet.py lines 155-161
// ---------------------------------------------------------------------------

/// Port of _tokens() with full STOPWORDS, WORD_RE, MIN_CONTENT_TOKEN_LEN.
pub fn tokens(text: &str) -> HashSet<String> {
    let raw: HashSet<String> = WORD_RE
        .find_iter(text.to_lowercase().as_str())
        .map(|m| m.as_str().to_string())
        .filter(|t| !STOPWORDS.contains(t.as_str()))
        .collect();
    raw.into_iter()
        .filter(|t| t.len() >= MIN_CONTENT_TOKEN_LEN)
        .collect()
}

// ---------------------------------------------------------------------------
// slugify - from utils.py (needed by _project_rows, _related_rows)
// ---------------------------------------------------------------------------

lazy_static! {
    static ref SLUGIFY_RE_1: Regex = Regex::new(r"[^a-z0-9]+").unwrap();
    static ref SLUGIFY_RE_2: Regex = Regex::new(r"-+").unwrap();
}

/// Port of utils.py slugify()
fn slugify(value: &str) -> String {
    let value = value.trim().to_lowercase();
    let value = SLUGIFY_RE_1.replace_all(&value, "-");
    let value = SLUGIFY_RE_2.replace_all(&value, "-");
    let value = value.trim_matches('-');
    if value.is_empty() {
        "general".to_string()
    } else {
        value.to_string()
    }
}

// ---------------------------------------------------------------------------
// IndexRow type for _project_rows, _global_rows, _related_rows
// ---------------------------------------------------------------------------

type IndexRow = HashMap<String, String>;

// ---------------------------------------------------------------------------
// _project_rows() - faithful port of context_packet.py lines 164-172
// ---------------------------------------------------------------------------

#[pyfunction]
#[pyo3(signature = (index_rows, project=None))]
pub fn project_rows(index_rows: Vec<IndexRow>, project: Option<String>) -> Vec<IndexRow> {
    let project = match project {
        Some(p) if !p.is_empty() => p,
        _ => return Vec::new(),
    };
    let slug = slugify(&project);
    let wanted = format!("/projects/{}.md", slug);
    let wanted_lower = wanted.to_lowercase();
    let mut rows: Vec<IndexRow> = index_rows
        .into_iter()
        .filter(|row| {
            row.get("tag").map(|s| s.as_str()) != Some("superseded")
                && row
                    .get("path")
                    .map(|p| p.to_lowercase() == wanted_lower)
                    .unwrap_or(false)
        })
        .collect();
    // Sort by (date, memory_id) descending
    rows.sort_by(|a, b| {
        let a_key = (
            a.get("date").map(|s| s.as_str()).unwrap_or(""),
            a.get("memory_id").map(|s| s.as_str()).unwrap_or(""),
        );
        let b_key = (
            b.get("date").map(|s| s.as_str()).unwrap_or(""),
            b.get("memory_id").map(|s| s.as_str()).unwrap_or(""),
        );
        b_key.cmp(&a_key) // descending
    });
    rows
}

// ---------------------------------------------------------------------------
// _global_rows() - faithful port of context_packet.py lines 175-180
// ---------------------------------------------------------------------------

#[pyfunction]
pub fn global_rows(index_rows: Vec<IndexRow>) -> Vec<IndexRow> {
    let allowed: HashSet<String> =
        ["/preferences.md", "/profile.md"].iter().map(|s| s.to_string()).collect();
    let mut rows: Vec<IndexRow> = index_rows
        .into_iter()
        .filter(|row| {
            row.get("tag").map(|s| s.as_str()) != Some("superseded")
                && row
                    .get("path")
                    .map(|p| allowed.contains(&p.to_lowercase()))
                    .unwrap_or(false)
        })
        .collect();
    // Sort by (path != "/profile.md", date) ascending (reverse=False in Python)
    rows.sort_by(|a, b| {
        let a_profile = a.get("path").map(|p| p.as_str()) != Some("/profile.md");
        let b_profile = b.get("path").map(|p| p.as_str()) != Some("/profile.md");
        let a_key = (
            a_profile,
            a.get("date").map(|s| s.as_str()).unwrap_or(""),
        );
        let b_key = (
            b_profile,
            b.get("date").map(|s| s.as_str()).unwrap_or(""),
        );
        a_key.cmp(&b_key) // ascending
    });
    rows
}

// ---------------------------------------------------------------------------
// _related_rows() - faithful port of context_packet.py lines 183-217
// ---------------------------------------------------------------------------

#[pyfunction]
#[pyo3(signature = (index_rows, prompt, project=None, limit=6))]
pub fn related_rows(
    index_rows: Vec<IndexRow>,
    prompt: String,
    project: Option<String>,
    limit: usize,
) -> Vec<IndexRow> {
    let query = tokens(&prompt);
    if query.is_empty() {
        return Vec::new();
    }
    let project_slug = project.map(|p| slugify(&p));
    let mut scored: Vec<(f64, IndexRow)> = Vec::new();

    for row in index_rows {
        if row.get("tag").map(|s| s.as_str()) == Some("superseded")
            || row.get("kind").map(|s| s.as_str()) == Some("session")
        {
            continue;
        }
        let path = row.get("path").map(|p| p.to_lowercase()).unwrap_or_default();

        // Foreign projects never leak in on word overlap alone (#56 boundary).
        if path.starts_with("/projects/")
            && project_slug.is_some()
            && path != format!("/projects/{}.md", project_slug.as_ref().unwrap())
        {
            continue;
        }
        if path.starts_with("/sessions/") {
            continue;
        }

        let subject_text = format!(
            "{} {}",
            row.get("subject").map(|s| s.as_str()).unwrap_or(""),
            row.get("text").map(|s| s.as_str()).unwrap_or("")
        );
        let row_tokens = tokens(&subject_text);
        let overlap: HashSet<_> = query.intersection(&row_tokens).collect();

        if overlap.len() < 2 {
            continue;
        }
        let score = overlap.len() as f64 / (1.0_f64).max(query.len() as f64);
        if score < 0.3 {
            continue;
        }
        scored.push((score, row));
    }

    // Sort by (score, date) descending
    scored.sort_by(|a, b| {
        let date_a = a.1.get("date").map(|s| s.as_str()).unwrap_or("");
        let date_b = b.1.get("date").map(|s| s.as_str()).unwrap_or("");
        let key_a = (a.0, date_a);
        let key_b = (b.0, date_b);
        key_b.partial_cmp(&key_a).unwrap_or(std::cmp::Ordering::Equal)
    });

    scored.into_iter().take(limit).map(|(_, row)| row).collect()
}

// ---------------------------------------------------------------------------
// TokenCache class - PyO3 exposed, faithful to _tokens behavior
// ---------------------------------------------------------------------------

/// TokenCache class in Rust with build() and query() methods.
/// Uses the same _tokens() logic (STOPWORDS, WORD_RE, MIN_CONTENT_TOKEN_LEN).
#[pyclass]
pub struct TokenCache {
    cache: Arc<Mutex<HashMap<String, (Vec<String>, HashSet<String>)>>>,
}

#[pymethods]
impl TokenCache {
    #[new]
    fn new() -> Self {
        TokenCache {
            cache: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    /// Build token cache for a batch of texts.
    /// texts: list of (memory_id, text) tuples
    fn build(&self, texts: Vec<(String, String)>) {
        let mut cache = self.cache.lock();
        cache.clear();
        for (id, text) in texts {
            let token_set = tokens(&text);
            let token_vec: Vec<String> = token_set.iter().cloned().collect();
            cache.insert(id, (token_vec, token_set));
        }
    }

    /// Query the token cache for related memory IDs.
    /// Uses the same scoring and filtering as _related_rows().
    /// prompt: the user's prompt text
    /// limit: max number of results
    /// Returns: list of (memory_id, score) sorted by relevance
    fn query(&self, prompt: String, limit: usize) -> Vec<(String, f64)> {
        let query = tokens(&prompt);
        if query.is_empty() {
            return Vec::new();
        }

        let cache = self.cache.lock();
        let mut scored: Vec<(String, f64)> = Vec::new();

        for (id, (_, token_set)) in cache.iter() {
            let overlap: HashSet<_> = query.intersection(token_set).collect();
            if overlap.len() < 2 {
                continue;
            }
            let score = overlap.len() as f64 / (query.len() as f64).sqrt().max(1.0);
            if score < 0.3 {
                continue;
            }
            scored.push((id.clone(), score));
        }

        // Sort by score descending (date not available in this simplified cache)
        scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
        scored.truncate(limit);
        scored
    }
}

// ---------------------------------------------------------------------------
// Standalone tokenize / tokenize_batch (PyO3 exposed)
// ---------------------------------------------------------------------------

/// Tokenize a single text into a vector of tokens (faithful to _tokens)
#[pyfunction]
pub fn tokenize(text: String) -> Vec<String> {
    tokens(&text).into_iter().collect()
}

/// Batch tokenize texts
#[pyfunction]
pub fn tokenize_batch(texts: Vec<String>) -> Vec<Vec<String>> {
    texts.iter().map(|t| tokens(t).into_iter().collect()).collect()
}
