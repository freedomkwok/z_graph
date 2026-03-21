# imp_graph scaffold

Starter structure modeled after `MiroFish`, with:

- `frontend`: React + Vite
- `backend`: FastAPI with dotenv-based config loading
- root npm workspace scripts to run/build both
- single root Dockerfile for both frontend + backend runtime

## Project structure

```text
imp_graph/
├── backend/
│   ├── app/
│   │   ├── core/
│   │   │   ├── api/
│   │   │   ├── manager/
│   │   │   ├── service/
│   │   │   ├── utils/
│   │   │   ├── component/
│   │   │   └── config.py
│   │   ├── application/
│   │   └── main.py
│   ├── package.json
│   └── requirements.txt
├── frontend/
│   ├── src/
│   └── package.json
├── Dockerfile
├── docker-compose.yml
└── package.json
```

## Local development

1. Install all JavaScript + Python dependencies:

```bash
npm run setup:all
```

2. If needed, install backend Python dependencies only:

```bash
npm run setup:backend
```

3. Start local mode (auto-checks PostgreSQL; starts it if missing):

```bash
npm run localmode
```

4. Start frontend + backend only (if PostgreSQL already running):

```bash
npm run dev
```

5. Start backend in debug mode (debugpy attach on port `5678`):

```bash
npm run backend:debug
```

Then run the VS Code launch config:
- `Attach Backend (debugpy:5678)`

6. Clean Python cache files:

```bash
npm run clean:pycache
```

## Docker

```bash
npm run docker:build
npm run docker:up
```

`npm run docker:up` starts local PostgreSQL only.
To start all compose services, run:

```bash
npm run docker:up:all
```

Then open:

- `http://localhost:8000` for the React app
- `http://localhost:8000/api/health` for backend health

Local PostgreSQL is included in Docker Compose:

- Host: `localhost`
- Port: `5432`
- Credentials and DB name are configured in `backend/.env.example`
- Inside Docker network, backend should use `POSTGRES_HOST=postgres`

Database environment variables:

- `POSTGRES_HOST`
- `POSTGRES_PORT`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_URL` (optional override)

Backend convention:

- Shared/reusable framework code lives in `backend/app/core`
- App-specific code goes into `backend/app/application`
