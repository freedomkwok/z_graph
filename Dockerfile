FROM node:20-alpine AS frontend-builder

WORKDIR /frontend
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
ARG PROJECT_DETAIL_REQUEST_TIMEOUT_MS=120000
ENV PROJECT_DETAIL_REQUEST_TIMEOUT_MS=${PROJECT_DETAIL_REQUEST_TIMEOUT_MS}
RUN npm run build

FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
# Required by ProjectManager startup schema initialization when STORAGE=postgres.
COPY database/init_tables.sql /database/init_tables.sql
# COPY backend/.env.example ./.env.example
COPY --from=frontend-builder /frontend/dist ./app/static

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
