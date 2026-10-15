"""Document metadata extraction + readability metrics for RFP intake.

Two responsibilities, both pure functions over the converted Markdown:

    extract_metadata()      parse the fields the TrackFlow CONTEXT expects
    compute_readability()   py-readability-metrics scores used to anticipate
                            processing cost (NOT as a literary grade)

Readability uses `py-readability-metrics` (`uv add py-readability-metrics`)
which relies on the NLTK `punkt_tab` corpus. We try to ensure it exists at
runtime and degrade gracefully (metrics = None) when offline — the pipeline
must never die because a corpus download failed.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

#: Rough tokens-per-word ratio used to estimate LLM cost before agents run.
TOKENS_PER_WORD = 1.3

#: Minimum words required by py-readability-metrics to compute any score.
_MIN_WORDS_FOR_METRICS = 100

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_KV_LINE_RE = re.compile(r"^\s*([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9 .,/()&%-]{0,60}?):\s*(\S.*)$")

#: Normalized keys we surface as first-class metadata fields.
_KV_ALIASES: dict[str, str] = {
    "rfp reference no": "rfp_reference",
    "rfp reference": "rfp_reference",
    "issuing organization": "issuing_organization",
    "organization": "issuing_organization",
    "date issued": "date_issued",
    "proposal due date": "proposal_due_date",
    "due date": "proposal_due_date",
    "subject": "subject",
}

_SPANISH_MARKERS = {
    "el", "la", "los", "las", "de", "que", "y", "en", "un", "una", "para",
    "con", "no", "se", "por", "solicitud", "propuesta", "almacenamiento",
    "gestión", "devoluciones", "transporte", "envíos", "cliente", "fecha",
}
_ENGLISH_MARKERS = {
    "the", "and", "for", "with", "our", "we", "you", "proposal", "shipping",
    "warehouse", "warehousing", "orders", "customer", "carrier", "date",
    "request", "partnership", "rates", "delivery",
}


@dataclass(frozen=True)
class RFPMetadata:
    """Metadata pulled from the converted Markdown (None when not present)."""

    title: str | None = None
    issuing_organization: str | None = None
    rfp_reference: str | None = None
    proposal_due_date: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    detected_language: str | None = None
    extra: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReadabilityMetrics:
    """Readability scores + token cost estimate for one document."""

    word_count: int
    flesch_kincaid_grade: float | None = None
    gunning_fog_index: float | None = None
    coleman_liau_index: float | None = None
    estimated_token_cost: int | None = None
    #: Populated when scores could not be computed (e.g. too short / offline).
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Metadata extraction ─────────────────────────────────────────────────


def _detect_language(text: str) -> str | None:
    tokens = re.findall(r"[a-záéíóúñü]+", text.lower())
    if not tokens:
        return None
    es = sum(1 for t in tokens if t in _SPANISH_MARKERS)
    en = sum(1 for t in tokens if t in _ENGLISH_MARKERS)
    if es == 0 and en == 0:
        return None
    return "es" if es >= en else "en"


def _first_line(markdown: str) -> str | None:
    for line in markdown.splitlines():
        cleaned = line.strip().lstrip("#").strip()
        if cleaned:
            return cleaned[:200]
    return None


def _extract_contact_name(markdown: str) -> str | None:
    """Best-effort contact name: after a 'Contact' heading or the 'Best,' sign-off."""
    lines = [line.strip() for line in markdown.splitlines()]

    def _candidate(next_line: str) -> str | None:
        if not next_line or "@" in next_line or len(next_line.split()) > 5:
            return None
        return next_line[:200]

    for i, line in enumerate(lines):
        if re.match(r"^#*\s*\d*\.?\s*contact\b", line, re.IGNORECASE):
            for nxt in lines[i + 1 : i + 4]:
                name = _candidate(nxt)
                if name:
                    return name
    for i, line in enumerate(lines):
        if re.match(r"^#*\s*best[,.]?\s*$", line, re.IGNORECASE):
            for nxt in lines[i + 1 : i + 4]:
                name = _candidate(nxt)
                if name:
                    return name
    return None


def extract_metadata(markdown: str) -> RFPMetadata:
    """Parse structured fields out of the converted Markdown.

    Only fields that literally appear in the document are returned — nothing
    is guessed. Unknown ``Key: Value`` pairs are kept in ``extra``.
    """
    key_values: dict[str, str] = {}
    for line in markdown.splitlines():
        match = _KV_LINE_RE.match(line)
        if not match:
            continue
        key = match.group(1).strip().lower().rstrip(".")
        value = match.group(2).strip()
        if value and key not in key_values:
            key_values[key] = value[:400]

    recognized: dict[str, str] = {}
    extra: dict[str, str] = {}
    for key, value in key_values.items():
        alias = _KV_ALIASES.get(key)
        if alias:
            recognized[alias] = value
        elif len(extra) < 20:
            extra[key] = value

    email_match = _EMAIL_RE.search(markdown)

    return RFPMetadata(
        title=_first_line(markdown),
        issuing_organization=recognized.get("issuing_organization"),
        rfp_reference=recognized.get("rfp_reference"),
        proposal_due_date=recognized.get("proposal_due_date"),
        contact_name=_extract_contact_name(markdown),
        contact_email=email_match.group(0) if email_match else None,
        detected_language=_detect_language(markdown),
        extra=extra,
    )


# ── Readability metrics ─────────────────────────────────────────────────


def _ensure_nltk_data() -> None:
    """Make sure the ``punkt_tab`` corpus is available; never raise."""
    try:
        import nltk

        nltk.data.find("tokenizers/punkt_tab")
    except LookupError:
        try:
            import nltk

            nltk.download("punkt_tab", quiet=True)
        except Exception:
            pass  # offline — compute_readability degrades gracefully
    except Exception:
        pass


def compute_readability(markdown: str) -> ReadabilityMetrics:
    """Score the Markdown with py-readability-metrics + estimate token cost.

    Scores are a *cost/effort proxy* for downstream agents, not a literary
    grade. Documents under 100 words (the library's hard minimum) or a failed
    corpus load return ``None`` scores with an explanatory ``note``.
    """
    word_count = len(markdown.split())
    estimated_tokens = int(word_count * TOKENS_PER_WORD)

    if word_count < _MIN_WORDS_FOR_METRICS:
        return ReadabilityMetrics(
            word_count=word_count,
            estimated_token_cost=estimated_tokens,
            note=f"Documento corto (<{_MIN_WORDS_FOR_METRICS} palabras): sin métricas de legibilidad.",
        )

    _ensure_nltk_data()
    try:
        from readability import Readability

        readability = Readability(markdown)
        return ReadabilityMetrics(
            word_count=word_count,
            flesch_kincaid_grade=round(readability.flesch_kincaid().score, 2),
            gunning_fog_index=round(readability.gunning_fog().score, 2),
            coleman_liau_index=round(readability.coleman_liau().score, 2),
            estimated_token_cost=estimated_tokens,
        )
    except Exception as exc:
        return ReadabilityMetrics(
            word_count=word_count,
            estimated_token_cost=estimated_tokens,
            note=f"No se pudieron calcular las métricas de legibilidad: {exc}",
        )
