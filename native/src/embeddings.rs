// native/src/embeddings.rs
use pyo3::prelude::*;

/// Compute cosine similarity between two vectors
#[pyfunction]
pub fn cosine_similarity(a: Vec<f32>, b: Vec<f32>) -> f64 {
    if a.len() != b.len() || a.is_empty() {
        return 0.0;
    }

    let mut dot = 0.0f64;
    let mut norm_a = 0.0f64;
    let mut norm_b = 0.0f64;

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

/// Compute top-k cosine similarities using matrix multiplication approach
/// query: the query embedding vector
/// matrix: list of embedding vectors to compare against
/// k: number of top results to return
/// Returns: list of (index, score) sorted by score descending
#[pyfunction]
pub fn cosine_top_k(query: Vec<f32>, matrix: Vec<Vec<f32>>, k: usize) -> Vec<(usize, f64)> {
    if matrix.is_empty() || k == 0 {
        return Vec::new();
    }

    let mut results: Vec<(usize, f64)> = matrix
        .iter()
        .enumerate()
        .map(|(idx, emb)| (idx, cosine_similarity(query.clone(), emb.clone())))
        .collect();

    results.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap());
    results.truncate(k);
    results
}

/// Batch compute pairwise cosine similarities for a single kind
/// Used by subject_audit to find semantic candidates
/// embeddings: list of (memory_id, embedding_vector) tuples
/// threshold: minimum similarity score to include in results
/// Returns: list of (id_a, id_b, score) for pairs above threshold
#[pyfunction]
pub fn pairwise_cosine(embeddings: Vec<(String, Vec<f32>)>, threshold: f64) -> Vec<(String, String, f64)> {
    let n = embeddings.len();
    if n < 2 {
        return Vec::new();
    }

    let mut results = Vec::new();

    for i in 0..n {
        for j in (i + 1)..n {
            let score = cosine_similarity(embeddings[i].1.clone(), embeddings[j].1.clone());
            if score >= threshold {
                results.push((embeddings[i].0.clone(), embeddings[j].0.clone(), score));
            }
        }
    }

    results
}

/// Normalize a vector to unit length
#[pyfunction]
pub fn normalize_vector(v: Vec<f32>) -> Vec<f32> {
    let mag: f64 = v.iter().map(|x| (*x as f64).powi(2)).sum::<f64>().sqrt();
    if mag < 1e-10 {
        return v;
    }
    v.iter().map(|x| (*x as f64 / mag) as f32).collect()
}

/// Compute dot product of two vectors
#[pyfunction]
pub fn dot_product(a: Vec<f32>, b: Vec<f32>) -> f64 {
    a.iter().zip(b.iter()).map(|(ai, bi)| (*ai as f64) * (*bi as f64)).sum()
}
