import pytest


@pytest.mark.parametrize(
    ("format", "data"),
    [
        ("csv", b"question,answer\nWhat?,This.\n"),
        ("json", b'[{"question":"What?","answer":"This."}]'),
        ("jsonl", b'{"question":"What?"}\n{"question":"Why?"}\n'),
    ],
)
def test_parse_supported_formats(format, data):
    from app.datasets import parse_dataset

    rows = parse_dataset(data, format, 10)
    assert rows[0]["question"] == "What?"


@pytest.mark.parametrize(
    ("format", "data"),
    [
        ("json", b"{bad"),
        ("jsonl", b'{"ok": 1}\n{bad'),
        ("json", b'["not-an-object"]'),
        ("csv", b""),
    ],
)
def test_parse_rejects_invalid_datasets(format, data):
    from app.datasets import parse_dataset

    with pytest.raises(ValueError):
        parse_dataset(data, format, 10)


def test_parse_rejects_row_limit():
    from app.datasets import parse_dataset

    with pytest.raises(ValueError, match="2 rows"):
        parse_dataset(b"a\n1\n2\n3\n", "csv", 2)
