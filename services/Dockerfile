# ── TrackFlow API – uv-optimized Dockerfile ────────────────────────────
# Uses Python slim image and uv for fast, reliable dependency installation.

FROM python:3.11-slim

# ── System libraries for WeasyPrint PDF rendering ──────────────────────
RUN apt-get update \
	&& apt-get install -y --no-install-recommends \
		fonts-dejavu-core \
		libffi8 \
		libglib2.0-0 \
		libharfbuzz-subset0 \
		libharfbuzz0b \
		libjpeg62-turbo \
		libopenjp2-7 \
		libpango-1.0-0 \
		libpangoft2-1.0-0 \
	&& rm -rf /var/lib/apt/lists/*

# ── Install uv (fast Python package installer) ──────────────────────────
# Official installation method: pip install uv
RUN pip install --no-cache-dir uv

# ── Working directory ───────────────────────────────────────────────────
WORKDIR /app

# ── Copy dependency manifests first (Docker layer caching) ──────────────
COPY api/requirements.txt requirements.txt

# ── Install system & Python dependencies ────────────────────────────────
# --system flag installs packages into the global Python environment
# inside the container (no virtualenv needed).
RUN uv pip install --system --no-cache-dir -r requirements.txt

# ── Copy application source code ────────────────────────────────────────
COPY api/ .
COPY telemetry/ /app/telemetry/
COPY reporting/ /app/reporting/

# ── Port ────────────────────────────────────────────────────────────────
EXPOSE 8000

# ── Default command: Uvicorn with hot-reload for development ────────────
CMD ["uvicorn", "src.fastapi_server:app", "--reload", "--host", "0.0.0.0", "--port", "8000"]