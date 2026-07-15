FROM python:3.12-slim

WORKDIR /app

# ca-certificates: outbound HTTPS calls (Google ID token verification, Gemini
# when a user's BYOK key is used) need a trusted cert store. Nothing here
# needs a compiler — PyMuPDF and uvicorn[standard]'s C-extension deps
# (uvloop, httptools, websockets) all ship manylinux wheels for this base.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY frontend/ frontend/

# backend/data/ and backend/storage/ are meant to be volumes (see
# docker-compose.yml) — created here too so a `docker run` without any
# volume attached still works instead of crashing on a missing directory.
RUN useradd --create-home --uid 1000 jetek \
    && mkdir -p backend/storage backend/data \
    && chown -R jetek:jetek /app
USER jetek

EXPOSE 7860

# Plain stdlib urllib instead of curl/wget — keeps the image slim, no extra
# apt package just for a healthcheck. /login is public (no auth) so this
# doesn't need a session cookie to succeed.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/login', timeout=3)" || exit 1

# Single worker, deliberately: main.py's lifespan spawns in-process asyncio
# background tasks (the 15-min storage sweep + nightly full cleanup) that
# would each run once per worker process if this were --workers N, redundantly
# racing the same SQLite file and storage directory. This app's scale (a
# handful of internal users) doesn't need more than one process anyway.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "7860"]
