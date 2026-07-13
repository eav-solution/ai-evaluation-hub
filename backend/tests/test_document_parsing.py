from io import BytesIO


def _minimal_pdf(text: str) -> bytes:
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


def _docx_bytes(paragraphs: list[str]) -> bytes:
    from docx import Document as DocxDocument

    buffer = BytesIO()
    document = DocxDocument()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    document.save(buffer)
    return buffer.getvalue()


def test_extract_text_txt_and_md():
    from app.documents import extract_text

    assert extract_text("hello\r\nworld".encode(), "txt") == "hello\nworld"
    assert extract_text(b"# Title\n\nBody text.", "md") == "# Title\n\nBody text."


def test_extract_text_html_strips_script_and_style():
    from app.documents import extract_text

    html = b"<html><head><style>p{}</style></head><body><script>x()</script><p>Visible text.</p></body></html>"
    text = extract_text(html, "html")
    assert "Visible text." in text
    assert "x()" not in text
    assert "p{}" not in text


def test_extract_text_pdf():
    from app.documents import extract_text

    text = extract_text(_minimal_pdf("Hello PDF world from EvalHub"), "pdf")
    assert "Hello PDF world from EvalHub" in text


def test_extract_text_pdf_in_isolated_process():
    from app.documents import extract_text_isolated

    text = extract_text_isolated(
        _minimal_pdf("Isolated PDF parsing"),
        "pdf",
        timeout_seconds=10,
    )
    assert "Isolated PDF parsing" in text


def test_extract_text_docx_paragraphs():
    from app.documents import extract_text

    text = extract_text(_docx_bytes(["First paragraph.", "Second paragraph."]), "docx")
    assert "First paragraph." in text
    assert "Second paragraph." in text


def test_extract_text_rejects_garbage_pdf():
    import pytest

    from app.documents import extract_text

    with pytest.raises(ValueError):
        extract_text(b"not a pdf at all", "pdf")


def test_extract_text_rejects_empty_document():
    import pytest

    from app.documents import extract_text

    with pytest.raises(ValueError):
        extract_text(b"   \n\n  ", "txt")


def test_extract_text_rejects_non_utf8_text():
    import pytest

    from app.documents import extract_text

    with pytest.raises(ValueError):
        extract_text(b"\xff\xfe\x00bad", "txt")


def test_extract_text_rejects_unknown_format():
    import pytest

    from app.documents import extract_text

    with pytest.raises(ValueError):
        extract_text(b"data", "xlsx")


def test_extract_text_enforces_pdf_page_limit():
    import pytest

    from app.documents import extract_text

    with pytest.raises(ValueError, match="page limit"):
        extract_text(_minimal_pdf("Too many pages"), "pdf", max_pages=0)


def test_extract_text_enforces_docx_expansion_limit():
    import pytest

    from app.documents import extract_text

    with pytest.raises(ValueError, match="expanded size limit"):
        extract_text(
            _docx_bytes(["Compressed document"]),
            "docx",
            max_expanded_bytes=1,
        )


def test_extract_text_enforces_character_limit():
    import pytest

    from app.documents import extract_text

    with pytest.raises(ValueError, match="text limit"):
        extract_text(b"long extracted text", "txt", max_chars=5)


def test_extract_text_stops_pdf_before_collecting_all_pages(monkeypatch):
    import pytest
    import pypdf

    from app.documents import extract_text

    calls = []

    class Page:
        def extract_text(self):
            calls.append(1)
            return "xxxx"

    class Reader:
        is_encrypted = False
        pages = [Page(), Page(), Page()]

    monkeypatch.setattr(pypdf, "PdfReader", lambda stream: Reader())
    with pytest.raises(ValueError, match="text limit"):
        extract_text(b"pdf", "pdf", max_chars=5)
    assert len(calls) == 2


def test_storage_keys():
    from app.documents import original_storage_key, text_storage_key

    assert original_storage_key("ws1", "doc1", "pdf") == "documents/ws1/doc1.pdf"
    assert text_storage_key("ws1", "doc1") == "documents/ws1/doc1.extracted.txt"


def test_new_settings_defaults():
    from app.config import Settings

    s = Settings()
    assert s.max_document_bytes == 20 * 1024 * 1024
    assert s.max_document_expanded_bytes == 100 * 1024 * 1024
    assert s.max_document_pages == 2000
    assert s.max_document_chars == 20_000_000
    assert s.document_parse_timeout_seconds == 30
    assert s.document_parse_memory_bytes == 512 * 1024 * 1024
    assert s.generation_lease_seconds == 900
    assert s.max_documents_per_job == 10
    assert s.generation_chunk_chars == 2000
    assert s.generation_context_chars == 300_000


def test_chunk_text_packs_paragraphs_up_to_limit():
    from app.documents import chunk_text

    paragraph_a = "a" * 900
    paragraph_b = "b" * 900
    paragraph_c = "c" * 900
    chunks = chunk_text(f"{paragraph_a}\n\n{paragraph_b}\n\n{paragraph_c}", 2000)
    assert len(chunks) == 2
    assert chunks[0] == f"{paragraph_a}\n\n{paragraph_b}"
    assert chunks[1] == paragraph_c


def test_chunk_text_splits_long_paragraph_on_sentences():
    from app.documents import chunk_text

    sentence = "This sentence is here. "
    text = (sentence * 200).strip()  # one huge paragraph, sentence boundaries inside
    chunks = chunk_text(text, 500)
    assert all(len(chunk) <= 500 for chunk in chunks)
    assert all(chunk.endswith(".") for chunk in chunks)


def test_chunk_text_hard_splits_pathological_text():
    from app.documents import chunk_text

    chunks = chunk_text("x" * 2500, 100)
    assert len(chunks) == 25
    assert all(len(chunk) == 100 for chunk in chunks)


def test_chunk_text_drops_tiny_chunks():
    from app.documents import chunk_text

    assert chunk_text("short", 2000) == []


def test_chunk_text_is_deterministic():
    from app.documents import chunk_text

    text = ("First paragraph with enough text to matter for chunking purposes.\n\n" * 40).strip()
    assert chunk_text(text, 300) == chunk_text(text, 300)
