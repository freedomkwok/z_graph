# zep_graph

`zep_graph` is a full-stack document-to-knowledge-graph builder.

- `frontend`: React + Vite UI for project selection, ontology generation, and graph build monitoring
- `backend`: FastAPI APIs that extract text, generate ontology with LLM, and build graph data in Zep
- `database`: SQL bootstrap for project storage when using Postgres
- root workspace scripts for setup, build, and utility commands

## Current workflow

1. Upload files and submit simulation requirement in UI Step A.
2. Backend calls `POST /api/ontology/generate` to extract ontology types.
3. Trigger UI Step B to call `POST /api/build`.
4. Backend creates a graph, sets ontology, ingests chunks, and polls processing status.
5. Frontend polls `GET /api/task/{task_id}` and can load graph counts from `GET /api/data/{graph_id}`.

## Project structure

```text
zep_graph/
├── frontend/                  # React + Vite app (default dev port 5173)
├── backend/                   # FastAPI app (default port 8000)
│   └── app/
│       ├── core/              # shared API/services/managers/utils
│       ├── application/        # app-specific extension point
│       └── main.py             # FastAPI entrypoint + optional static hosting
├── database/
│   ├── init_tables.sql
│   └── init_tables.py
├── Dockerfile                 # builds frontend and serves via backend
├── docker-compose.yml         # app + postgres
└── package.json               # npm workspace root
```

## Prerequisites

- Node.js 20+
- Python 3.11+
- `uv` for Python dependency sync (`pip install uv` if needed)
- Docker (optional, for containerized run)

## Environment configuration

Create backend app env file:

```bash
cp backend/.env.example backend/.env
```

Create database init env file:

```bash
cp database/.env.example database/.env
```

Minimum required backend keys for end-to-end graph build:

- `LLM_API_KEY`
- `ZEP_API_KEY`

Optional backend keys:

- `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`
- Postgres keys when using `STORAGE=postgres`

Database bootstrap/init keys (`POSTGRES_HOST_PORT`, `DB_INIT_AUTO_PROVISION`, `POSTGRES_BOOTSTRAP_*`, etc.) live in `database/.env`.

## Local development (recommended)

Install all JS + Python dependencies:

```bash
npm run setup:all
```

Start backend:

```bash
npm run dev --workspace backend
```

Start frontend (new terminal):

```bash
npm run dev --workspace frontend
```

Open:

- Frontend: `http://localhost:5173`
- Backend health: `http://localhost:8000/api/health`

Vite proxies `/api` to backend on `http://localhost:8000`.

## Backend debug mode

```bash
npm run dev:debug --workspace backend
```

Then attach with VS Code launch config: `Attach Backend (debugpy:5678)`.

## Storage modes

Default mode is file-based storage (`STORAGE=file`) under `backend/uploads`.

To use Postgres runtime:

1. Set `STORAGE=postgres` in `backend/.env`
2. Initialize schema:

```bash
npm run db:init
```

`db:init` will:

1. Load DB init variables from `database/.env` (fallback: `database/.env.example`)
2. Try to start Docker `postgres` (`docker compose up -d postgres`)
3. Fall back to an existing local Postgres if Docker startup is skipped/fails
4. Auto-provision the target user/database (if missing), then apply schema

### Quick recipes

1) If `5432` is occupied, run Docker Postgres on another port:

Set in `database/.env`:

```bash
POSTGRES_HOST_PORT=55432
```

Or one-off:

```bash
POSTGRES_HOST_PORT=55432 npm run db:init
```

2) Reuse existing Langfuse Postgres (`localhost:5432`) and auto-provision DB/user:

Set in `database/.env`:

```bash
DB_INIT_AUTO_PROVISION=true
POSTGRES_BOOTSTRAP_URL=postgresql://postgres:postgres@localhost:5432/postgres
```

Then run:

```bash
npm run db:init
```

`init_tables.py` will create/alter the target role (`POSTGRES_USER`), create `POSTGRES_DB` if missing, grant privileges, and apply `database/init_tables.sql`.

## Docker

Build and run all services:

```bash
docker compose up --build
```

Open:

- App: `http://localhost:8000`
- Health: `http://localhost:8000/api/health`

Notes:

- Compose defines `postgres` and `app` services.
- Current compose file reads environment from `backend/.env.example`.

## API quick reference

- `GET /api/health`
- `GET /api/project/list`
- `GET /api/project/{project_id}`
- `POST /api/ontology/generate` (multipart form with files + requirement)
- `POST /api/build`
- `GET /api/task/{task_id}`
- `GET /api/data/{graph_id}`
- `DELETE /api/project/{project_id}`
- `DELETE /api/delete/{graph_id}`

## Useful root scripts

- `npm run setup:all` - install workspace deps + backend Python deps via `uv`
- `npm run db:up` - start only Docker Postgres (`POSTGRES_HOST_PORT` supported)
- `npm run db:init` - start/fallback Postgres, auto-provision role+db, then initialize schema
- `npm run build` - build frontend and run backend install step
- `npm run start` - run frontend preview (4173) and backend start (8000)
- `npm run kill:dev` - kill common frontend/backend dev processes
- `npm run clean:pycache` - remove Python cache artifacts
