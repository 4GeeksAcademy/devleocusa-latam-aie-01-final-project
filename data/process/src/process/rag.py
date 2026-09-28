"""
TrackFlow RAG – Data processing module
========================================
Responsibilities:
  - setup():  Read source docs → chunk → embed → index into Qdrant
  - embed():  Generate a vector for a single text using the dedicated embeddings model

Collection name: trackflow-knowledge-base
Idempotency strategy: CLEAN AND RELOAD — every run deletes the collection
and recreates it from scratch. This is simple, deterministic, and avoids
duplicate points in development.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

# ── Load environment variables ─────────────────────────────────────────
# Walk up from this file until we find a .env (project root)
_env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_env_path)

# ── Configuration ──────────────────────────────────────────────────────
QDRANT_URL: str = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION_NAME: str = os.getenv("QDRANT_COLLECTION", "trackflow-knowledge-base")
EMBEDDINGS_MODEL_ID: str = os.getenv("EMBEDDINGS_MODEL_ID", "text-embedding-3-small")
EMBEDDINGS_API_KEY: str = os.getenv("EMBEDDINGS_API_KEY", "")
EMBEDDINGS_BASE_URL: str = os.getenv("EMBEDDINGS_BASE_URL", "https://api.openai.com/v1")
COMPANY_NAME: str = "TrackFlow"

# Default path to the knowledge base corpus
DEFAULT_CORPUS_DIR: Path = Path(__file__).resolve().parents[2] / "docs" / "company-knowledge-base"

# Embedding dimension for text-embedding-3-small
EMBEDDING_DIMENSION: int = 1536


# ── Embeddings client ──────────────────────────────────────────────────
_embedding_client: Optional[OpenAI] = None


def _get_embedding_client() -> OpenAI:
    """Lazy-init the OpenAI client used exclusively for embeddings."""
    global _embedding_client
    if _embedding_client is None:
        _embedding_client = OpenAI(
            api_key=EMBEDDINGS_API_KEY,
            base_url=EMBEDDINGS_BASE_URL,
        )
    return _embedding_client


def embed(text: str) -> list[float]:
    """Generate an embedding vector for *text* using the dedicated embeddings model.

    This same function is used both when indexing chunks and when encoding
    the user query — ensuring consistent vectors on both sides.

    Args:
        text: The text to embed.

    Returns:
        A list of floats representing the embedding vector.
    """
    client = _get_embedding_client()
    response = client.embeddings.create(
        model=EMBEDDINGS_MODEL_ID,
        input=text,
    )
    return response.data[0].embedding


# ── Chunking ───────────────────────────────────────────────────────────

def _chunk_markdown(text: str, source_filename: str, max_chunk_tokens: int = 400) -> list[dict]:
    """Split a Markdown document into semantic chunks.

    Strategy: split by Markdown headers (## or ###). If a section is too
    long, split it further by paragraph boundaries. Each chunk is a dict
    with metadata suitable for the Qdrant payload.

    Args:
        text: Raw Markdown content.
        source_filename: Name of the source file (for metadata).
        max_chunk_tokens: Approximate max tokens per chunk (heuristic: 1 token ≈ 4 chars).

    Returns:
        List of chunk dicts with keys: text, section, source_document,
        company, language, chunk_index.
    """
    language = "es" if ".es." in source_filename else "en"

    # Extract title from first line or first heading
    title_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    doc_title = title_match.group(1).strip() if title_match else source_filename

    chunks: list[dict] = []

    # Split by level-2 or level-3 headings
    # Pattern: find lines that start with ## or ###
    sections = re.split(r"\n(?=#{1,3}\s)", text)

    chunk_index = 0
    for section in sections:
        section = section.strip()
        if not section:
            continue

        # Extract section heading
        heading_match = re.match(r"^#{1,3}\s+(.+)$", section, re.MULTILINE)
        section_name = heading_match.group(1).strip() if heading_match else doc_title

        # Estimate token count (rough: 1 token ≈ 4 chars for Spanish)
        est_tokens = len(section) // 4

        if est_tokens <= max_chunk_tokens:
            # Section fits in one chunk
            chunks.append({
                "text": section,
                "section": section_name,
                "source_document": source_filename,
                "company": COMPANY_NAME,
                "language": language,
                "chunk_index": chunk_index,
            })
            chunk_index += 1
        else:
            # Split by paragraphs (double newline)
            paragraphs = re.split(r"\n\n+", section)
            current_chunk = ""
            for para in paragraphs:
                para = para.strip()
                if not para:
                    continue
                # Check if adding this paragraph would exceed the limit
                if current_chunk and (len(current_chunk + "\n\n" + para)) // 4 > max_chunk_tokens:
                    # Flush current chunk
                    chunks.append({
                        "text": current_chunk,
                        "section": section_name,
                        "source_document": source_filename,
                        "company": COMPANY_NAME,
                        "language": language,
                        "chunk_index": chunk_index,
                    })
                    chunk_index += 1
                    current_chunk = para
                else:
                    current_chunk = current_chunk + "\n\n" + para if current_chunk else para

            # Flush remaining content
            if current_chunk:
                chunks.append({
                    "text": current_chunk,
                    "section": section_name,
                    "source_document": source_filename,
                    "company": COMPANY_NAME,
                    "language": language,
                    "chunk_index": chunk_index,
                })
                chunk_index += 1

    return chunks


def _deterministic_id(source_document: str, chunk_index: int) -> int:
    """Generate a deterministic integer ID from source document + chunk index.

    This ensures idempotency: the same document+chunk always gets the same ID.
    We use this as the Qdrant point ID so re-indexing overwrites existing points.
    """
    raw = f"{source_document}::{chunk_index}"
    h = hashlib.sha256(raw.encode()).hexdigest()
    # Take first 16 hex chars → fits in uint64
    return int(h[:16], 16)


# ── setup() ────────────────────────────────────────────────────────────

def setup(corpus_dir: Optional[Path] = None) -> dict:
    """Read source documents, chunk, embed, and index into Qdrant.

    Idempotency strategy: **CLEAN AND RELOAD** — the collection is deleted
    and recreated on every run. Point IDs are deterministic (SHA-256 of
    source_document + chunk_index) so the same content always gets the
    same ID, but since we drop the collection first, duplicates are
    impossible.

    Args:
        corpus_dir: Path to the folder containing source documents.
                    Defaults to docs/company-knowledge-base/.

    Returns:
        A summary dict with stats about the indexing run.
    """
    corpus_dir = corpus_dir or DEFAULT_CORPUS_DIR

    # 1. Discover source files
    supported_extensions = {".md", ".txt", ".rst"}
    source_files = sorted(
        f for f in corpus_dir.iterdir()
        if f.is_file() and f.suffix in supported_extensions
    )

    if not source_files:
        raise FileNotFoundError(f"No documents found in {corpus_dir}")

    # 2. Parse and chunk all documents
    all_chunks: list[dict] = []
    for source_file in source_files:
        content = source_file.read_text(encoding="utf-8")
        chunks = _chunk_markdown(content, source_file.name)
        all_chunks.extend(chunks)

    if not all_chunks:
        raise ValueError("Chunking produced zero chunks — check your documents.")

    # 3. Connect to Qdrant
    qdrant = QdrantClient(url=QDRANT_URL)

    # 4. Drop and recreate collection (idempotent clean-and-reload)
    if qdrant.collection_exists(COLLECTION_NAME):
        qdrant.delete_collection(COLLECTION_NAME)

    qdrant.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(
            size=EMBEDDING_DIMENSION,
            distance=Distance.COSINE,
        ),
    )

    # 5. Embed all chunks
    points: list[PointStruct] = []
    for chunk in all_chunks:
        vector = embed(chunk["text"])
        point_id = _deterministic_id(chunk["source_document"], chunk["chunk_index"])
        points.append(
            PointStruct(
                id=point_id,
                vector=vector,
                payload=chunk,
            )
        )

    # 6. Insert into Qdrant (batch for efficiency)
    BATCH_SIZE = 50
    for i in range(0, len(points), BATCH_SIZE):
        qdrant.upsert(
            collection_name=COLLECTION_NAME,
            points=points[i : i + BATCH_SIZE],
        )

    # 7. Return summary
    doc_names = list({c["source_document"] for c in all_chunks})
    return {
        "collection": COLLECTION_NAME,
        "documents_indexed": len(doc_names),
        "document_names": doc_names,
        "total_chunks": len(all_chunks),
        "embedding_model": EMBEDDINGS_MODEL_ID,
        "qdrant_url": QDRANT_URL,
    }


# ── CLI entry point ────────────────────────────────────────────────────

if __name__ == "__main__":
    result = setup()
    print("✅ Setup complete!")
    print(f"   Collection : {result['collection']}")
    print(f"   Documents  : {result['documents_indexed']}")
    print(f"   Chunks     : {result['total_chunks']}")
    print(f"   Embed model: {result['embedding_model']}")
