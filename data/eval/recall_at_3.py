"""
TrackFlow RAG — Recall@3 Evaluation
====================================
Measures whether the correct source document chunk appears in the top-3
retrieved results for each test query.

Run (needs Qdrant running):
  cd data/pipelines && uv run python -m eval.recall_at_3

Run from repo root:
  cd data/pipelines && uv run python eval/recall_at_3.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────
EVAL_DIR = Path(__file__).resolve().parent
QUERIES_PATH = EVAL_DIR / "test-queries.json"
CORPUS_DIR = EVAL_DIR.parent.parent / "docs" / "company-knowledge-base"


def _chunk_corpus() -> dict[str, str]:
    """Load and chunk the corpus, returning {source_document: full_text}."""
    chunks: dict[str, str] = {}
    for f in sorted(CORPUS_DIR.iterdir()):
        if f.is_file() and f.suffix in {".md", ".txt", ".rst"}:
            chunks[f.name] = f.read_text(encoding="utf-8")
    return chunks


def _simple_retrieve(
    question: str,
    corpus: dict[str, str],
    k: int = 3,
) -> list[dict]:
    """Offline keyword-based retrieval (no Qdrant needed).

    Splits each document into paragraphs and scores by keyword overlap
    with the question. This is an approximation — the real retrieval uses
    embeddings. For CI validation it's sufficient to verify that the
    expected document contains the most relevant paragraph.
    """
    results: list[dict] = []
    q_tokens = set(question.lower().split())

    for doc_name, doc_text in corpus.items():
        paragraphs = [p.strip() for p in doc_text.split("\n\n") if p.strip()]
        for para in paragraphs:
            p_tokens = set(para.lower().split())
            overlap = len(q_tokens & p_tokens)
            results.append({
                "text": para,
                "source_document": doc_name,
                "score": overlap,
            })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:k]


def evaluate_recall_at_3(
    use_live_qdrant: bool = False,
) -> dict:
    """Run Recall@3 evaluation.

    Args:
        use_live_qdrant: If True, uses the real retrieve() from the pipeline.
                          If False (default), uses offline keyword matching.

    Returns:
        A dict with per-query results and the final Recall@3 metric.
    """
    # Load test queries
    queries = json.loads(QUERIES_PATH.read_text(encoding="utf-8"))

    if use_live_qdrant:
        from data.pipelines.src.pipelines.rag import retrieve as live_retrieve

        def _retrieve(q: str) -> list[dict]:
            return live_retrieve(q, k=3, min_score=0.0)
    else:
        corpus = _chunk_corpus()

        def _retrieve(q: str) -> list[dict]:
            return _simple_retrieve(q, corpus, k=3)

    results: list[dict] = []
    hits = 0

    for query in queries:
        retrieved = _retrieve(query["question"])
        top3_sources = [r["source_document"] for r in retrieved]
        expected = query["expected_source_document"]
        found = expected in top3_sources

        if found:
            hits += 1

        results.append({
            "id": query["id"],
            "question": query["question"],
            "expected": expected,
            "top3_sources": top3_sources,
            "hit": found,
        })

    recall_at_3 = hits / len(queries) if queries else 0.0

    return {
        "total_queries": len(queries),
        "hits": hits,
        "recall_at_3": recall_at_3,
        "threshold": 0.8,
        "passed": recall_at_3 >= 0.8,
        "details": results,
    }


def main() -> None:
    """CLI entry point."""
    use_live = "--live" in sys.argv
    mode = "LIVE Qdrant" if use_live else "offline keyword matching"

    print(f"📊 TrackFlow RAG — Recall@3 Evaluation ({mode})")
    print("=" * 60)

    report = evaluate_recall_at_3(use_live_qdrant=use_live)

    for detail in report["details"]:
        status = "✅" if detail["hit"] else "❌"
        print(f"  {status} [{detail['id']}] {detail['question'][:60]}...")
        print(f"     Expected: {detail['expected']}")
        print(f"     Top-3:    {detail['top3_sources']}")
        print()

    print("=" * 60)
    print(f"  Hits:           {report['hits']}/{report['total_queries']}")
    print(f"  Recall@3:       {report['recall_at_3']:.0%}")
    print(f"  Threshold:      {report['threshold']:.0%}")
    print(f"  Result:         {'✅ PASSED' if report['passed'] else '❌ FAILED'}")
    print("=" * 60)

    # Save report
    report_path = EVAL_DIR / "recall_at_3_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n📄 Report saved to {report_path}")

    sys.exit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
