// native/src/tokenization.rs
use pyo3::prelude::*;
use regex::Regex;
use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use parking_lot::Mutex;

/// Batch tokenization cache for memory texts
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

    /// Build token cache for a batch of texts
    /// texts: list of (memory_id, text) tuples
    fn build(&self, texts: Vec<(String, String)>) {
        let word_re = Regex::new(r"[a-z0-9_]{2,}").unwrap();
        let stopwords: HashSet<&str> = [
            "the", "be", "to", "of", "and", "a", "in", "that", "have", "i",
            "it", "for", "not", "on", "with", "he", "as", "you", "do", "at",
            "this", "but", "his", "by", "from", "they", "we", "say", "her", "she",
            "or", "an", "will", "my", "one", "all", "would", "there", "their",
            "what", "so", "up", "out", "if", "about", "who", "get", "which", "go",
            "me", "when", "make", "can", "like", "time", "no", "just", "him", "know",
            "take", "people", "into", "year", "your", "good", "some", "could", "them",
            "see", "other", "than", "then", "now", "look", "only", "come", "its", "over",
            "think", "also", "back", "after", "use", "two", "how", "our", "work",
            "first", "well", "way", "even", "new", "want", "because", "any", "these",
            "give", "day", "most", "us", "are", "has", "was", "were", "been", "has",
            "had", "does", "did", "doing", "done", "being", "am", "is", "are", "was",
        ]
        .iter()
        .cloned()
        .collect();

        let mut cache = self.cache.lock();
        for (id, text) in texts {
            let tokens: Vec<String> = word_re
                .find_iter(&text.to_lowercase())
                .map(|m| m.as_str().to_string())
                .filter(|t| !stopwords.contains(t.as_str()))
                .collect();
            let token_set: HashSet<String> = tokens.iter().cloned().collect();
            cache.insert(id, (tokens, token_set));
        }
    }

    /// Query the token cache for related memory IDs
    /// prompt: the user's prompt text
    /// limit: max number of results
    /// Returns: list of (memory_id, score) sorted by relevance
    fn query(&self, prompt: String, limit: usize) -> Vec<(String, f64)> {
        let word_re = Regex::new(r"[a-z0-9_]{2,}").unwrap();
        let stopwords: HashSet<&str> = [
            "the", "be", "to", "of", "and", "a", "in", "that", "have", "i",
            "it", "for", "not", "on", "with", "he", "as", "you", "do", "at",
        ]
        .iter()
        .cloned()
        .collect();

        let prompt_tokens: HashSet<String> = word_re
            .find_iter(&prompt.to_lowercase())
            .map(|m| m.as_str().to_string())
            .filter(|t| !stopwords.contains(t.as_str()))
            .collect();

        if prompt_tokens.is_empty() {
            return Vec::new();
        }

        let cache = self.cache.lock();
        let mut results: Vec<(String, f64)> = cache
            .iter()
            .map(|(id, (_, token_set))| {
                let intersection: HashSet<_> = prompt_tokens.intersection(token_set).collect();
                let score = intersection.len() as f64
                    / (prompt_tokens.len().max(1) as f64).ln_1p();
                (id.clone(), score)
            })
            .filter(|(_, score)| *score > 0.0)
            .collect();

        results.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap());
        results.truncate(limit);
        results
    }
}

/// Tokenize a single text into a set of tokens
#[pyfunction]
pub fn tokenize(text: String) -> Vec<String> {
    let word_re = Regex::new(r"[a-z0-9_]{2,}").unwrap();
    let stopwords: HashSet<&str> = [
        "the", "be", "to", "of", "and", "a", "in", "that", "have", "i",
        "it", "for", "not", "on", "with", "he", "as", "you", "do", "at",
    ]
    .iter()
    .cloned()
    .collect();

    word_re
        .find_iter(&text.to_lowercase())
        .map(|m| m.as_str().to_string())
        .filter(|t| !stopwords.contains(t.as_str()))
        .collect()
}

/// Batch tokenize texts
#[pyfunction]
pub fn tokenize_batch(texts: Vec<String>) -> Vec<Vec<String>> {
    let word_re = Regex::new(r"[a-z0-9_]{2,}").unwrap();
    let stopwords: HashSet<&str> = [
        "the", "be", "to", "of", "and", "a", "in", "that", "have", "i",
        "it", "for", "not", "on", "with", "he", "as", "you", "do", "at",
    ]
    .iter()
    .cloned()
    .collect();

    texts
        .iter()
        .map(|text| {
            word_re
                .find_iter(&text.to_lowercase())
                .map(|m| m.as_str().to_string())
                .filter(|t| !stopwords.contains(t.as_str()))
                .collect()
        })
        .collect()
}
