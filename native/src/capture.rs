// native/src/capture.rs - simplified without uuid/chrono
use pyo3::prelude::*;
use rusqlite::{params, Connection, OptionalExtension};
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;
use parking_lot::Mutex;

/// Capture buffer with connection pooling
#[pyclass]
pub struct CaptureBuffer {
    conn: Arc<Mutex<Connection>>,
}

/// Capture payload
#[pyclass]
pub struct CapturePayload {
    #[pyo3(get, set)]
    pub session_id: String,
    #[pyo3(get, set)]
    pub hook_event_name: String,
    #[pyo3(get, set)]
    pub cwd: String,
    #[pyo3(get, set)]
    pub tool: Option<String>,
    #[pyo3(get, set)]
    pub input_summary: Option<String>,
    #[pyo3(get, set)]
    pub output_summary: Option<String>,
    #[pyo3(get, set)]
    pub transcript_path: Option<String>,
    #[pyo3(get, set)]
    pub model: Option<String>,
    #[pyo3(get, set)]
    pub source: Option<String>,
    #[pyo3(get, set)]
    pub reason: Option<String>,
}

#[pymethods]
impl CapturePayload {
    #[new]
    pub fn new(session_id: String, hook_event_name: String, cwd: String) -> Self {
        CapturePayload {
            session_id,
            hook_event_name,
            cwd,
            tool: None,
            input_summary: None,
            output_summary: None,
            transcript_path: None,
            model: None,
            source: None,
            reason: None,
        }
    }
}

/// Generate a simple unique ID
fn generate_id() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let duration = SystemTime::now().duration_since(UNIX_EPOCH).unwrap();
    let nanos = duration.as_nanos();
    let mut result = String::with_capacity(20);
    result.push_str("obs_");
    let mut n = nanos;
    const ALPHABET: &[u8] = b"0123456789abcdef";
    for _ in 0..16 {
        result.push(ALPHABET[(n & 0xf) as usize] as char);
        n >>= 4;
    }
    result
}

/// Get current timestamp as ISO string
fn now_iso() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let duration = SystemTime::now().duration_since(UNIX_EPOCH).unwrap();
    let secs = duration.as_secs();
    let nanos = duration.subsec_nanos();
    let days = secs / 86400;
    let secs_of_day = secs % 86400;
    let hours = secs_of_day / 3600;
    let mins = (secs_of_day % 3600) / 60;
    let secs = secs_of_day % 60;
    format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}.{:09}Z",
        1970 + days / 365,
        (days % 365) / 30 + 1,
        (days % 365) % 30 + 1,
        hours,
        mins,
        secs,
        nanos
    )
}

#[pymethods]
impl CaptureBuffer {
    #[new]
    fn new(vault_path: String) -> PyResult<Self> {
        let db_path = PathBuf::from(&vault_path)
            .join(".ai-memory-hub")
            .join("observations.sqlite3");

        let conn = Connection::open(&db_path).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyIOError, _>(format!("Failed to open DB: {}", e))
        })?;

        conn.execute_batch(
            "PRAGMA journal_mode=WAL;
             PRAGMA synchronous=NORMAL;
             PRAGMA cache_size=10000;
             PRAGMA temp_store=MEMORY;",
        ).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("PRAGMA failed: {}", e))
        })?;

        conn.execute(
            "CREATE TABLE IF NOT EXISTS observations (
                observation_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                hook_event_name TEXT NOT NULL,
                cwd TEXT,
                tool TEXT,
                input_summary TEXT,
                output_summary TEXT,
                transcript_path TEXT,
                model TEXT,
                source TEXT,
                reason TEXT,
                created_at TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                attempts INTEGER DEFAULT 0,
                claim_token TEXT
            )",
            [],
        ).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("CREATE failed: {}", e))
        })?;

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_obs_session ON observations(session_id, status)",
            [],
        ).ok();
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_obs_status ON observations(status, created_at)",
            [],
        ).ok();

        Ok(CaptureBuffer {
            conn: Arc::new(Mutex::new(conn)),
        })
    }

    /// Append a capture event
    pub fn append(&self, payload: &CapturePayload) -> PyResult<String> {
        let id = generate_id();
        let created_at = now_iso();

        let mut conn = self.conn.lock();
        let tx = conn.transaction().map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Transaction failed: {}", e))
        })?;

        tx.execute(
            "INSERT INTO observations 
             (observation_id, session_id, hook_event_name, cwd, tool, input_summary, 
              output_summary, transcript_path, model, source, reason, created_at, status)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, 'pending')",
            params![
                &id,
                &payload.session_id,
                &payload.hook_event_name,
                &payload.cwd,
                &payload.tool,
                &payload.input_summary,
                &payload.output_summary,
                &payload.transcript_path,
                &payload.model,
                &payload.source,
                &payload.reason,
                &created_at,
            ],
        ).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("INSERT failed: {}", e))
        })?;

        tx.commit().map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Commit failed: {}", e))
        })?;

        Ok(id)
    }

    /// Claim pending observations for processing
    pub fn claim(&self, session_id: &str, limit: usize, claim_token: &str) -> PyResult<Vec<String>> {
        let mut conn = self.conn.lock();
        let tx = conn.transaction().map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Transaction failed: {}", e))
        })?;

        let mut stmt = tx
            .prepare(
                "SELECT observation_id FROM observations 
             WHERE session_id = ?1 AND status IN ('pending', 'failed')
             ORDER BY created_at LIMIT ?2",
            )
            .map_err(|e| {
                PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("SELECT failed: {}", e))
            })?;

        let ids: Vec<String> = stmt
            .query_map(params![session_id, &limit.to_string()], |row| {
                row.get::<_, String>(0)
            })
            .map_err(|e| {
                PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Query failed: {}", e))
            })?
            .filter_map(|r| r.ok())
            .collect();

        drop(stmt);

        if !ids.is_empty() {
            let placeholders: Vec<String> = ids.iter().map(|_| "?".to_string()).collect();
            let sql = format!(
                "UPDATE observations SET status = 'processing', claim_token = ?1, attempts = attempts + 1
                 WHERE observation_id IN ({})",
                placeholders.join(",")
            );
            let mut dyn_params: Vec<&dyn rusqlite::ToSql> = vec![&claim_token];
            for id in &ids {
                dyn_params.push(id);
            }
            let param_refs: &[&dyn rusqlite::ToSql] = &dyn_params;
            tx.execute(&sql, param_refs)
                .map_err(|e| {
                    PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("UPDATE failed: {}", e))
                })?;
        }

        tx.commit().map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Commit failed: {}", e))
        })?;

        Ok(ids)
    }

    /// Mark observations as completed
    pub fn mark_completed(&self, ids: Vec<String>) -> PyResult<usize> {
        if ids.is_empty() {
            return Ok(0);
        }

        let mut conn = self.conn.lock();
        let placeholders: Vec<String> = ids.iter().map(|_| "?".to_string()).collect();
        let sql = format!(
            "UPDATE observations SET status = 'completed' WHERE observation_id IN ({})",
            placeholders.join(",")
        );
        let params: Vec<&dyn rusqlite::ToSql> =
            ids.iter().map(|s| s as &dyn rusqlite::ToSql).collect();

        let affected = conn.execute(&sql, &*params).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("UPDATE failed: {}", e))
        })?;

        Ok(affected)
    }

    /// Get buffer statistics
    pub fn stats(&self) -> PyResult<HashMap<String, i64>> {
        let conn = self.conn.lock();
        let mut stats = HashMap::new();

        let pending: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM observations WHERE status = 'pending'",
                [],
                |row| row.get(0),
            )
            .optional()
            .unwrap_or(Some(0))
            .unwrap_or(0);
        stats.insert("pending".to_string(), pending);

        let processing: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM observations WHERE status = 'processing'",
                [],
                |row| row.get(0),
            )
            .optional()
            .unwrap_or(Some(0))
            .unwrap_or(0);
        stats.insert("processing".to_string(), processing);

        let completed: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM observations WHERE status = 'completed'",
                [],
                |row| row.get(0),
            )
            .optional()
            .unwrap_or(Some(0))
            .unwrap_or(0);
        stats.insert("completed".to_string(), completed);

        Ok(stats)
    }
}

/// Create a new capture buffer
#[pyfunction]
pub fn capture_buffer(vault_path: String) -> PyResult<CaptureBuffer> {
    CaptureBuffer::new(vault_path)
}
