-- zep_graph project storage schema
CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    project_data JSONB NOT NULL,
    extracted_text TEXT
);

CREATE INDEX IF NOT EXISTS idx_projects_created_at ON projects (created_at DESC);