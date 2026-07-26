use serde::{Deserialize, Serialize};
use std::fs;
use std::path::Path;

const DEFAULT_CONTEXT_FILES: &[&str] = &["CLAUDE.md", "README.md", "package.json"];
const MAX_FILE_SIZE: usize = 2000;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ContextFile {
    pub path: String,
    pub content: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProjectContext {
    pub project_name: Option<String>,
    pub files: Vec<ContextFile>,
}

pub fn load_project_context(project_dir: &str) -> ProjectContext {
    let dir = Path::new(project_dir);
    let project_name = dir
        .file_name()
        .map(|n| n.to_string_lossy().to_string());

    let mut files = Vec::new();
    for &filename in DEFAULT_CONTEXT_FILES {
        let file_path = dir.join(filename);
        if file_path.exists() {
            if let Ok(content) = fs::read_to_string(&file_path) {
                let truncated = if content.len() > MAX_FILE_SIZE {
                    content[..MAX_FILE_SIZE].to_string()
                } else {
                    content
                };
                files.push(ContextFile {
                    path: filename.to_string(),
                    content: truncated,
                });
            }
        }
    }

    ProjectContext {
        project_name,
        files,
    }
}
