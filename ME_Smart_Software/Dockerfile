# ══════════════════════════════════════════════════════
#  ME Smart Backend  (FastAPI + Uvicorn)
#
#  Build context: root of ME_Smart_Software/
#  Run via podman compose (backend/docker-compose.yml)
# ══════════════════════════════════════════════════════
FROM python:3.12-slim

WORKDIR /app

# Install deps first (cache layer — only re-runs when requirements.txt changes)
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy backend source
COPY backend/ backend/

# Copy static frontend (FastAPI serves these at /ui via StaticFiles)
# server.py resolves STATIC_DIR = dirname(__file__)/..)  →  /app
COPY *.html ./
COPY *.png  ./

WORKDIR /app/backend

EXPOSE 8000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
