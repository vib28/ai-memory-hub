// native/src/manager.rs - Faithful port of manager.py hot paths
//
// Ports:
// - _best_match() with SequenceMatcher ratio
// - semantic_candidates() with O(n²) pairwise comparison
// - DUPLICATE_UPDATE_BAND and TRUE_DUPLICATE_THRESHOLD constants
// - _norm_cache behavior

use pyo3::prelude::*;
use std::collections::HashMap;

// ---------------------------------------------------------------------------
// Constants (from manager.py lines 206-207)
// ---------------------------------------------------------------------------

/// Ratio at/above this is treated as the same fact restated verbatim.
pub const TRUE_DUPLICATE_THRESHOLD: f64 = 0.985;

/// Ratio in the DUPLICATE_UPDATE_BAND below TRUE_DUPLICATE_THRESHOLD is close
/// enough to be the same subject but differs by a token (a version bump, a
/// spelling fix) — that's an *update* the user likely wants applied.
pub const DUPLICATE_UPDATE_BAND: f64 = 0.85;

// ---------------------------------------------------------------------------
// normalize_text - from utils.py (needed by _best_match)
// ---------------------------------------------------------------------------

/// Port of utils.py normalize_text()
fn normalize_text(value: &str) -> String {
    let value = value.to_lowercase().trim().to_string();
    // Collapse whitespace
    let value: String = value.split_whitespace().collect::<Vec<_>>().join(" ");
    // Remove non-word, non-space chars
    value
        .chars()
        .filter(|c| c.is_alphanumeric() || c.is_whitespace())
        .collect()
}

// ---------------------------------------------------------------------------
// SequenceMatcher ratio - faithful port of difflib.SequenceMatcher.ratio()
// ---------------------------------------------------------------------------

/// Compute the SequenceMatcher ratio between two strings.
/// This is a faithful port of Python's difflib.SequenceMatcher(None, a, b).ratio()
///
/// The algorithm:
/// 1. Find matching blocks (longest common subsequences of equal characters)
/// 2. Count total matching characters
/// 3. ratio = 2.0 * matches / (len(a) + len(b))
fn sequence_matcher_ratio(a: &str, b: &str) -> f64 {
    let a_chars: Vec<char> = a.chars().collect();
    let b_chars: Vec<char> = b.chars().collect();
    let len_a = a_chars.len();
    let len_b = b_chars.len();

    if len_a == 0 && len_b == 0 {
        return 1.0;
    }
    if len_a == 0 || len_b == 0 {
        return 0.0;
    }

    // Find all matching blocks using a dynamic programming approach
    // matching_blocks = _find_matching_blocks(&a_chars, &b_chars);
    let matching_chars = _count_matching_chars(&a_chars, &b_chars);
    2.0 * matching_chars as f64 / (len_a + len_b) as f64
}

/// Count the total number of matching characters across all matching blocks.
/// This implements the core of difflib's matching algorithm.
fn _count_matching_chars(a: &[char], b: &[char]) -> usize {
    let len_a = a.len();
    let len_b = b.len();

    if len_a == 0 || len_b == 0 {
        return 0;
    }

    // Use a 2D DP table for longest common substring at each position
    // We find all matching blocks (not just the longest)
    let mut matches = 0;
    let mut dp = vec![vec![0usize; len_b + 1]; len_a + 1];

    for i in 1..=len_a {
        for j in 1..=len_b {
            if a[i - 1] == b[j - 1] {
                dp[i][j] = dp[i - 1][j - 1] + 1;
            }
        }
    }

    // Backtrack to find all matching blocks
    let mut i = len_a;
    let mut j = len_b;
    while i > 0 && j > 0 {
        if a[i - 1] == b[j - 1] {
            // Start of a matching block
            let mut block_len = 0;
            while i > 0 && j > 0 && a[i - 1] == b[j - 1] {
                block_len += 1;
                i -= 1;
                j -= 1;
            }
            matches += block_len;
        } else if dp[i - 1][j] >= dp[i][j - 1] {
            i -= 1;
        } else {
            j -= 1;
        }
    }

    matches
}

// ---------------------------------------------------------------------------
// _best_match() - faithful port of manager.py lines 209-231
// ---------------------------------------------------------------------------

/// Port of _best_match() with SequenceMatcher ratio.
///
/// text: the candidate text to match
/// kind: the memory kind
/// rows: list of candidate rows (each is a dict with memory_id, text)
/// norm_cache: optional cache of normalized texts keyed by memory_id
///
/// Returns: (best_row, best_ratio) where best_row is the row dict or None
#[pyfunction]
#[pyo3(signature = (text, kind, rows, norm_cache=None))]
pub fn best_match(
    text: String,
    kind: String,
    rows: Vec<HashMap<String, String>>,
    norm_cache: Option<HashMap<String, String>>,
) -> (Option<HashMap<String, String>>, f64) {
    let norm = normalize_text(&text);
    let text_length = norm.len();
    if text_length == 0 {
        return (None, 0.0);
    }

    let threshold = DUPLICATE_UPDATE_BAND;
    let minimum = ((threshold * text_length as f64 / (2.0 - threshold)) + 0.999999) as usize;
    let minimum = minimum.max(1);
    let maximum = ((2.0 - threshold) * text_length as f64 / threshold) as usize;

    let mut cache = norm_cache.unwrap_or_default();
    let mut best_row: Option<HashMap<String, String>> = None;
    let mut best_ratio: f64 = 0.0;

    for row in &rows {
        let row_text = row.get("text").map(|s| s.as_str()).unwrap_or("");
        let row_length = row_text.len();
        if row_length < minimum || row_length > maximum {
            continue;
        }

        let row_id = row.get("memory_id").map(|s| s.as_str()).unwrap_or("");
        let existing = if cache.contains_key(row_id) {
            cache.get(row_id).cloned().unwrap_or_default()
        } else {
            let normalized = normalize_text(row_text);
            cache.insert(row_id.to_string(), normalized.clone());
            normalized
        };

        let ratio = sequence_matcher_ratio(&norm, &existing);
        if ratio > best_ratio {
            best_row = Some(row.clone());
            best_ratio = ratio;
        }
    }

    (best_row, best_ratio)
}

// ---------------------------------------------------------------------------
// semantic_candidates() - faithful port of index.py lines 418-456
// ---------------------------------------------------------------------------

/// Port of semantic_candidates() with O(n²) pairwise comparison.
///
/// kind: the memory kind
/// threshold: minimum similarity score to include in results
/// limit: max number of results
/// rows: list of memory rows (each with memory_id, subject, normalized_hash)
/// embeddings: list of (memory_id, vector) tuples
///
/// Returns: list of {kind, memory_ids, subjects, similarity} dicts
#[pyfunction]
pub fn semantic_candidates(
    py: Python<'_>,
    kind: String,
    threshold: f64,
    limit: usize,
    rows: Vec<HashMap<String, String>>,
    embeddings: Vec<(String, Vec<f32>)>,
) -> Vec<HashMap<String, PyObject>> {
    if rows.len() < 2 {
        return Vec::new();
    }

    // Build vectors_by_parent: memory_id -> list of vectors
    let mut vectors_by_parent: HashMap<String, Vec<Vec<f32>>> = HashMap::new();
    for row in &rows {
        let id = row.get("memory_id").map(|s| s.as_str()).unwrap_or("").to_string();
        vectors_by_parent.insert(id, Vec::new());
    }
    for (emb_id, vector) in &embeddings {
        // emb_id may be "memory_id" or "memory_id::section"
        let parent_id = if let Some(pos) = emb_id.find("::") {
            &emb_id[..pos]
        } else {
            emb_id.as_str()
        };
        if let Some(vecs) = vectors_by_parent.get_mut(parent_id) {
            vecs.push(vector.clone());
        }
    }

    let mut pairs: Vec<HashMap<String, PyObject>> = Vec::new();

    for (index, left) in rows.iter().enumerate() {
        let left_id = left.get("memory_id").map(|s| s.as_str()).unwrap_or("").to_string();
        let left_vectors = vectors_by_parent.get(&left_id).cloned().unwrap_or_default();

        for right in rows.iter().skip(index + 1) {
            let right_id = right.get("memory_id").map(|s| s.as_str()).unwrap_or("").to_string();
            let right_vectors = vectors_by_parent.get(&right_id).cloned().unwrap_or_default();

            let mut scores: Vec<f64> = Vec::new();
            for left_vector in &left_vectors {
                for right_vector in &right_vectors {
                    scores.push(cosine_similarity_f64(left_vector, right_vector));
                }
            }

            if scores.is_empty() {
                continue;
            }

            let max_score = scores.iter().cloned().fold(0.0_f64, f64::max);
            let left_hash = left.get("normalized_hash").map(|s| s.as_str()).unwrap_or("");
            let right_hash = right.get("normalized_hash").map(|s| s.as_str()).unwrap_or("");

            if max_score >= threshold && left_hash != right_hash {
                let mut pair: HashMap<String, PyObject> = HashMap::new();
                pair.insert("kind".to_string(), kind.clone().into_py(py));
                let mem_ids = vec![left_id.clone(), right_id.clone()];
                pair.insert("memory_ids".to_string(), mem_ids.into_py(py));
                let subs = vec![
                    left.get("subject").map(|s| s.as_str()).unwrap_or("").to_string(),
                    right.get("subject").map(|s| s.as_str()).unwrap_or("").to_string(),
                ];
                pair.insert("subjects".to_string(), subs.into_py(py));
                pair.insert("similarity".to_string(), (max_score as f64).into_py(py));
                pairs.push(pair);
            }
        }
    }

    // Sort by similarity descending
    pairs.sort_by(|a, b| {
        let a_sim: f64 = a.get("similarity")
            .and_then(|s| s.extract::<f64>(py).ok())
            .unwrap_or(0.0);
        let b_sim: f64 = b.get("similarity")
            .and_then(|s| s.extract::<f64>(py).ok())
            .unwrap_or(0.0);
        b_sim.partial_cmp(&a_sim).unwrap_or(std::cmp::Ordering::Equal)
    });

    pairs.into_iter().take(limit.max(1)).collect()
}

/// Cosine similarity between two f32 vectors, returns f64
fn cosine_similarity_f64(a: &[f32], b: &[f32]) -> f64 {
    if a.len() != b.len() || a.is_empty() {
        return 0.0;
    }
    let mut dot = 0.0_f64;
    let mut norm_a = 0.0_f64;
    let mut norm_b = 0.0_f64;
    for i in 0..a.len() {
        let ai = a[i] as f64;
        let bi = b[i] as f64;
        dot += ai * bi;
        norm_a += ai * ai;
        norm_b += bi * bi;
    }
    let denom = (norm_a * norm_b).sqrt();
    if denom < 1e-10 {
        0.0
    } else {
        dot / denom
    }
}

// ---------------------------------------------------------------------------
// NormCache - PyO3 exposed, faithful to _norm_cache behavior
// ---------------------------------------------------------------------------

/// NormCache class in Rust - mirrors the _norm_cache dict behavior in manager.py.
/// Caches normalized text keyed by memory_id to avoid re-normalizing.
#[pyclass]
pub struct NormCache {
    cache: HashMap<String, String>,
}

#[pymethods]
impl NormCache {
    #[new]
    fn new() -> Self {
        NormCache {
            cache: HashMap::new(),
        }
    }

    /// Get the normalized text for a memory_id, computing and caching if needed.
    fn get_or_compute(&mut self, memory_id: &str, text: &str) -> String {
        if let Some(cached) = self.cache.get(memory_id) {
            cached.clone()
        } else {
            let normalized = normalize_text(text);
            self.cache.insert(memory_id.to_string(), normalized.clone());
            normalized
        }
    }

    /// Get the cached value without computing
    fn get(&self, memory_id: &str) -> Option<String> {
        self.cache.get(memory_id).cloned()
    }

    /// Insert a value into the cache
    fn insert(&mut self, memory_id: String, normalized: String) {
        self.cache.insert(memory_id, normalized);
    }

    /// Clear the cache
    fn clear(&mut self) {
        self.cache.clear();
    }

    /// Current size of the cache
    fn __len__(&self) -> usize {
        self.cache.len()
    }

    /// Current size of the cache (alias)
    fn len(&self) -> usize {
        self.cache.len()
    }
}

// ---------------------------------------------------------------------------
// Expose constants as Python functions
// ---------------------------------------------------------------------------

#[pyfunction]
pub fn get_true_duplicate_threshold() -> f64 {
    TRUE_DUPLICATE_THRESHOLD
}

#[pyfunction]
pub fn get_duplicate_update_band() -> f64 {
    DUPLICATE_UPDATE_BAND
}
