pub mod claude;

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StructureResult {
    pub original: String,
    pub structured: String,
}
