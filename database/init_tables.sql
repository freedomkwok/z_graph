-- z_graph project storage schema
CREATE TABLE IF NOT EXISTS prompt_labels (
    id BIGINT PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
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
    has_built_graph BOOLEAN NOT NULL DEFAULT FALSE,
    prompt_label_id BIGINT NULL REFERENCES prompt_labels (id),
    prompt_label VARCHAR(100)
);

CREATE TABLE IF NOT EXISTS ontology_versions (
    id BIGSERIAL PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects (project_id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    ontology_json JSONB NOT NULL,
    ontology_hash TEXT NOT NULL,
    parent_version_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_by_task_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS graph_build (
    task_id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL DEFAULT 'graph_build',
    project_id TEXT NULL REFERENCES projects (project_id) ON DELETE SET NULL,
    graph_id TEXT,
    graph_name TEXT,
    graph_backend TEXT,
    chunk_mode TEXT,
    chunk_size INTEGER,
    chunk_overlap INTEGER,
    status TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    error TEXT,
    result JSONB,
    progress_detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_text_hash TEXT,
    ontology_hash TEXT,
    ontology_version_id BIGINT REFERENCES ontology_versions (id),
    build_identity_key TEXT,
    batch_size INTEGER,
    total_chunks INTEGER,
    total_batches INTEGER,
    last_completed_batch_index INTEGER NOT NULL DEFAULT -1,
    resume_state TEXT NOT NULL DEFAULT 'new',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

ALTER TABLE prompt_labels
ADD COLUMN IF NOT EXISTS project_id TEXT;

ALTER TABLE prompt_labels
ADD COLUMN IF NOT EXISTS id BIGINT;

CREATE SEQUENCE IF NOT EXISTS prompt_labels_id_seq;

ALTER TABLE prompt_labels
ALTER COLUMN id SET DEFAULT nextval('prompt_labels_id_seq');

UPDATE prompt_labels
SET
    id = nextval('prompt_labels_id_seq')
WHERE
    id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_prompt_labels_id_unique ON prompt_labels (id);

ALTER TABLE projects ADD COLUMN IF NOT EXISTS zep_graph_id TEXT;

ALTER TABLE projects ADD COLUMN IF NOT EXISTS graph_backend TEXT;

ALTER TABLE projects ADD COLUMN IF NOT EXISTS project_workspace_id TEXT;

ALTER TABLE projects ADD COLUMN IF NOT EXISTS zep_graph_address TEXT;

ALTER TABLE projects ADD COLUMN IF NOT EXISTS has_built_graph BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE projects
ADD COLUMN IF NOT EXISTS prompt_label VARCHAR(100) REFERENCES prompt_labels (name);

ALTER TABLE projects
ADD COLUMN IF NOT EXISTS prompt_label_id BIGINT REFERENCES prompt_labels (id);

ALTER TABLE prompt_labels
ALTER COLUMN name TYPE VARCHAR(100);

ALTER TABLE projects
ALTER COLUMN prompt_label TYPE VARCHAR(100);

UPDATE projects AS p
SET
    prompt_label_id = l.id
FROM prompt_labels AS l
WHERE
    p.prompt_label_id IS NULL
    AND p.prompt_label IS NOT NULL
    AND LOWER(p.prompt_label) = LOWER(l.name);

ALTER TABLE graph_build
ADD COLUMN IF NOT EXISTS task_type TEXT NOT NULL DEFAULT 'graph_build';

ALTER TABLE graph_build
ADD COLUMN IF NOT EXISTS project_id TEXT NULL;

ALTER TABLE graph_build
ADD COLUMN IF NOT EXISTS graph_id TEXT;

ALTER TABLE graph_build
ADD COLUMN IF NOT EXISTS graph_name TEXT;

ALTER TABLE graph_build
ADD COLUMN IF NOT EXISTS graph_backend TEXT;

ALTER TABLE graph_build
ADD COLUMN IF NOT EXISTS chunk_mode TEXT;

ALTER TABLE graph_build
ADD COLUMN IF NOT EXISTS chunk_size INTEGER;

ALTER TABLE graph_build
ADD COLUMN IF NOT EXISTS chunk_overlap INTEGER;

ALTER TABLE graph_build
ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'pending';

ALTER TABLE graph_build
ADD COLUMN IF NOT EXISTS progress INTEGER NOT NULL DEFAULT 0;

ALTER TABLE graph_build
ADD COLUMN IF NOT EXISTS message TEXT NOT NULL DEFAULT '';

ALTER TABLE graph_build
ADD COLUMN IF NOT EXISTS error TEXT;

ALTER TABLE graph_build
ADD COLUMN IF NOT EXISTS result JSONB;

ALTER TABLE graph_build
ADD COLUMN IF NOT EXISTS progress_detail JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE graph_build
ADD COLUMN IF NOT EXISTS source_text_hash TEXT;

ALTER TABLE graph_build
ADD COLUMN IF NOT EXISTS ontology_hash TEXT;

ALTER TABLE graph_build
ADD COLUMN IF NOT EXISTS ontology_version_id BIGINT;

ALTER TABLE graph_build
ADD COLUMN IF NOT EXISTS build_identity_key TEXT;

ALTER TABLE graph_build
ADD COLUMN IF NOT EXISTS batch_size INTEGER;

ALTER TABLE graph_build
ADD COLUMN IF NOT EXISTS total_chunks INTEGER;

ALTER TABLE graph_build
ADD COLUMN IF NOT EXISTS total_batches INTEGER;

ALTER TABLE graph_build
ADD COLUMN IF NOT EXISTS last_completed_batch_index INTEGER NOT NULL DEFAULT -1;

ALTER TABLE graph_build
ADD COLUMN IF NOT EXISTS resume_state TEXT NOT NULL DEFAULT 'new';

ALTER TABLE graph_build
ADD COLUMN IF NOT EXISTS created_at TEXT NOT NULL DEFAULT NOW()::TEXT;

ALTER TABLE graph_build
ADD COLUMN IF NOT EXISTS updated_at TEXT NOT NULL DEFAULT NOW()::TEXT;

ALTER TABLE graph_build
DROP COLUMN IF EXISTS metadata;

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

CREATE INDEX IF NOT EXISTS idx_projects_created_at ON projects (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_projects_zep_graph_id ON projects (zep_graph_id);

CREATE INDEX IF NOT EXISTS idx_projects_graph_backend ON projects (graph_backend);

CREATE INDEX IF NOT EXISTS idx_projects_workspace_id ON projects (project_workspace_id);

CREATE INDEX IF NOT EXISTS idx_projects_has_built_graph ON projects (has_built_graph);

CREATE INDEX IF NOT EXISTS idx_projects_prompt_label ON projects (prompt_label);

CREATE INDEX IF NOT EXISTS idx_projects_prompt_label_id ON projects (prompt_label_id);

CREATE INDEX IF NOT EXISTS idx_prompt_labels_project_id ON prompt_labels (project_id);

CREATE INDEX IF NOT EXISTS idx_graph_build_project_id ON graph_build (project_id);

CREATE INDEX IF NOT EXISTS idx_graph_build_status ON graph_build (status);

CREATE INDEX IF NOT EXISTS idx_graph_build_created_at ON graph_build (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_graph_build_project_status_updated_at
ON graph_build (project_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_graph_build_identity_updated_at
ON graph_build (build_identity_key, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_graph_build_ontology_version_id
ON graph_build (ontology_version_id);

CREATE INDEX IF NOT EXISTS idx_ontology_versions_project_id_created_at
ON ontology_versions (project_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ontology_versions_project_hash
ON ontology_versions (project_id, ontology_hash);