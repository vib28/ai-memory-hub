// native/src/lib.rs
use pyo3::prelude::*;

pub mod tokenization;
pub mod embeddings;
pub mod capture;

/// AI Memory Hub native Rust extensions
#[pymodule]
fn ai_memory_hub_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Tokenization
    m.add_class::<tokenization::TokenCache>()?;
    m.add_function(wrap_pyfunction!(tokenization::tokenize, m)?)?;
    m.add_function(wrap_pyfunction!(tokenization::tokenize_batch, m)?)?;
    
    // Embeddings
    m.add_function(wrap_pyfunction!(embeddings::cosine_similarity, m)?)?;
    m.add_function(wrap_pyfunction!(embeddings::cosine_top_k, m)?)?;
    m.add_function(wrap_pyfunction!(embeddings::pairwise_cosine, m)?)?;
    m.add_function(wrap_pyfunction!(embeddings::normalize_vector, m)?)?;
    m.add_function(wrap_pyfunction!(embeddings::dot_product, m)?)?;
    
    // Capture
    m.add_class::<capture::CaptureBuffer>()?;
    m.add_class::<capture::CapturePayload>()?;
    m.add_function(wrap_pyfunction!(capture::capture_buffer, m)?)?;
    
    Ok(())
}
