-- z_graph project storage schema
CREATE TABLE IF NOT EXISTS prompt_labels (
    name TEXT PRIMARY KEY,
    project_id TEXT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prompt_label_stats (
    stats_key TEXT PRIMARY KEY,
    total_labels INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    project_data JSONB NOT NULL,
    extracted_text TEXT,
    zep_graph_id TEXT,
    graph_backend TEXT,
    project_workspace_id TEXT,
    zep_graph_address TEXT,
    prompt_label TEXT REFERENCES prompt_labels (name)
);

ALTER TABLE prompt_labels
ADD COLUMN IF NOT EXISTS project_id TEXT;

ALTER TABLE projects ADD COLUMN IF NOT EXISTS zep_graph_id TEXT;

ALTER TABLE projects ADD COLUMN IF NOT EXISTS graph_backend TEXT;

ALTER TABLE projects ADD COLUMN IF NOT EXISTS project_workspace_id TEXT;

ALTER TABLE projects ADD COLUMN IF NOT EXISTS zep_graph_address TEXT;

ALTER TABLE projects
ADD COLUMN IF NOT EXISTS prompt_label TEXT REFERENCES prompt_labels (name);

INSERT INTO
    prompt_labels (name, project_id, created_at, updated_at)
VALUES (
        'Production',
        NULL,
        NOW()::TEXT,
        NOW()::TEXT
    ),
    (
        'Medical',
        NULL,
        NOW()::TEXT,
        NOW()::TEXT
    )
ON CONFLICT (name) DO NOTHING;

INSERT INTO
    prompt_label_stats (stats_key, total_labels, updated_at)
VALUES (
        'global',
        (
            SELECT COUNT(*)::INT
            FROM prompt_labels
        ),
        NOW()::TEXT
    )
ON CONFLICT (stats_key) DO UPDATE SET
    total_labels = EXCLUDED.total_labels,
    updated_at = EXCLUDED.updated_at;

UPDATE projects
SET
    prompt_label = 'Production'
WHERE
    prompt_label IS NULL;

CREATE INDEX IF NOT EXISTS idx_projects_created_at ON projects (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_projects_zep_graph_id ON projects (zep_graph_id);

CREATE INDEX IF NOT EXISTS idx_projects_graph_backend ON projects (graph_backend);

CREATE INDEX IF NOT EXISTS idx_projects_workspace_id ON projects (project_workspace_id);

CREATE INDEX IF NOT EXISTS idx_projects_prompt_label ON projects (prompt_label);

CREATE INDEX IF NOT EXISTS idx_prompt_labels_project_id ON prompt_labels (project_id);