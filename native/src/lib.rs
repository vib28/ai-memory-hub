// native/src/lib.rs
use pyo3::prelude::*;

pub mod tokenization;
pub mod embeddings;
pub mod capture;
pub mod manager;

/// AI Memory Hub native Rust extensions
#[pymodule]
fn ai_memory_hub_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Tokenization
    m.add_class::<tokenization::TokenCache>()?;
    m.add_function(wrap_pyfunction!(tokenization::tokenize, m)?)?;
    m.add_function(wrap_pyfunction!(tokenization::tokenize_batch, m)?)?;
    m.add_function(wrap_pyfunction!(tokenization::project_rows, m)?)?;
    m.add_function(wrap_pyfunction!(tokenization::global_rows, m)?)?;
    m.add_function(wrap_pyfunction!(tokenization::related_rows, m)?)?;

    // Embeddings
    m.add_function(wrap_pyfunction!(embeddings::cosine_similarity, m)?)?;
    m.add_function(wrap_pyfunction!(embeddings::cosine_top_k, m)?)?;
    m.add_function(wrap_pyfunction!(embeddings::pairwise_cosine, m)?)?;
    m.add_function(wrap_pyfunction!(embeddings::normalize_vector, m)?)?;
    m.add_function(wrap_pyfunction!(embeddings::dot_product, m)?)?;

    // Capture
    m.add_class::<capture::Observation>()?;
    m.add_class::<capture::ObservationBuffer>()?;
    m.add_function(wrap_pyfunction!(capture::create_observation_buffer, m)?)?;
    m.add_function(wrap_pyfunction!(capture::normalize_event, m)?)?;
    m.add_function(wrap_pyfunction!(capture::normalize_client, m)?)?;
    m.add_function(wrap_pyfunction!(capture::sanitize_text, m)?)?;
    m.add_function(wrap_pyfunction!(capture::sanitize_payload, m)?)?;

    // Manager
    m.add_class::<manager::NormCache>()?;
    m.add_function(wrap_pyfunction!(manager::best_match, m)?)?;
    m.add_function(wrap_pyfunction!(manager::semantic_candidates, m)?)?;
    m.add_function(wrap_pyfunction!(manager::get_true_duplicate_threshold, m)?)?;
    m.add_function(wrap_pyfunction!(manager::get_duplicate_update_band, m)?)?;

    Ok(())
}
