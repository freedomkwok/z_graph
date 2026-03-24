-- zep_graph project storage schema
CREATE TABLE IF NOT EXISTS prompt_labels (
    name TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    project_data JSONB NOT NULL,
    extracted_text TEXT,
    zep_graph_id TEXT,
    project_workspace_id TEXT,
    zep_graph_address TEXT,
    prompt_label TEXT REFERENCES prompt_labels (name)
);

ALTER TABLE projects ADD COLUMN IF NOT EXISTS zep_graph_id TEXT;

ALTER TABLE projects ADD COLUMN IF NOT EXISTS project_workspace_id TEXT;

ALTER TABLE projects ADD COLUMN IF NOT EXISTS zep_graph_address TEXT;

ALTER TABLE projects
ADD COLUMN IF NOT EXISTS prompt_label TEXT REFERENCES prompt_labels (name);

INSERT INTO
    prompt_labels (name, created_at, updated_at)
VALUES (
        'Production',
        NOW()::TEXT,
        NOW()::TEXT
    ),
    (
        'Medical',
        NOW()::TEXT,
        NOW()::TEXT
    )
ON CONFLICT (name) DO NOTHING;

UPDATE projects
SET
    prompt_label = 'Production'
WHERE
    prompt_label IS NULL;

CREATE INDEX IF NOT EXISTS idx_projects_created_at ON projects (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_projects_zep_graph_id ON projects (zep_graph_id);

CREATE INDEX IF NOT EXISTS idx_projects_workspace_id ON projects (project_workspace_id);

CREATE INDEX IF NOT EXISTS idx_projects_prompt_label ON projects (prompt_label);