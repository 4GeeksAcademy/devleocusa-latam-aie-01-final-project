# ── TrackFlow API – uv-optimized Dockerfile ────────────────────────────
# Uses Python slim image and uv for fast, reliable dependency installation.

FROM python:3.12-slim

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
COPY services/api/requirements.txt requirements.txt

# ── Install system & Python dependencies ────────────────────────────────
# --system flag installs packages into the global Python environment
# inside the container (no virtualenv needed).
RUN uv pip install --system --no-cache-dir -r requirements.txt

# ── Copy application source code ────────────────────────────────────────
COPY services/api/ .
COPY services/telemetry/ /app/telemetry/
COPY services/reporting/ /app/reporting/
# RFP intake is a local package, not a PyPI dependency. Include it in the
# image so production works without the development-only Compose bind mount.
COPY data/pipelines/src/ /app/data/pipelines/src/

# ── Port ────────────────────────────────────────────────────────────────
EXPOSE 8000

# ── Default command: Uvicorn with hot-reload for development ────────────
CMD ["uvicorn", "src.fastapi_server:app", "--reload", "--host", "0.0.0.0", "--port", "8000"]