"""PDF → Markdown conversion for the RFP intake flow.

Every RFP arrives as PDF. Converting to Markdown *before* any agent reads the
document cuts token cost and noise substantially, and gives the readability
scorer clean prose to work with.

We use MarkItDown (`uv add 'markitdown[pdf]'`); any equivalent PDF→Markdown
step would satisfy the same contract documented in the ticket.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class ConversionError(Exception):
    """Raised when a PDF cannot be converted into usable Markdown.

    The runner maps this to a terminal ticket state (`descartado`) with the
    message stored in ``error_detail`` — failures are never silent.
    """


@dataclass(frozen=True)
class ConversionResult:
    """Outcome of a successful PDF → Markdown conversion."""

    markdown_path: Path
    word_count: int
    char_count: int


def convert_pdf_to_markdown(pdf_path: Path, output_dir: Path) -> ConversionResult:
    """Convert ``pdf_path`` to Markdown and persist it under ``output_dir``.

    The Markdown file is written next to the ticket artifacts (typically
    ``data/raw/<ticket_id>/``) so the pipeline never re-parses the PDF.

    Raises:
        ConversionError: missing file, non-PDF input, empty/unscanned PDF or
            any MarkItDown failure. The message is safe to show to Ventas.
    """
    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)

    if not pdf_path.is_file():
        raise ConversionError(f"No existe el archivo PDF: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ConversionError(f"Formato no soportado (se espera PDF): {pdf_path.suffix}")

    try:
        from markitdown import MarkItDown

        converted = MarkItDown().convert(str(pdf_path))
        markdown = (converted.text_content or "").strip()
    except ConversionError:
        raise
    except Exception as exc:  # MarkItDown raises several converter-specific types
        raise ConversionError(f"No se pudo convertir el PDF a Markdown: {exc}") from exc

    if not markdown:
        raise ConversionError(
            "El PDF no contiene texto extraible (¿documento escaneado como imagen?). "
            "No se puede analizar sin OCR."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / f"{pdf_path.stem}.md"
    markdown_path.write_text(markdown, encoding="utf-8")

    return ConversionResult(
        markdown_path=markdown_path,
        word_count=len(markdown.split()),
        char_count=len(markdown),
    )
