import csv
import json
from io import StringIO


def parse_dataset(data: bytes, format: str, max_rows: int) -> list[dict]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Dataset must be UTF-8 encoded") from exc

    try:
        if format == "csv":
            rows = list(csv.DictReader(StringIO(text)))
        elif format == "json":
            rows = json.loads(text)
            if not isinstance(rows, list):
                raise ValueError("JSON dataset must be an array")
        elif format == "jsonl":
            rows = [json.loads(line) for line in text.splitlines() if line.strip()]
        else:
            raise ValueError(f"Unsupported dataset format: {format}")
    except (csv.Error, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid {format.upper()} dataset") from exc

    if not rows:
        raise ValueError("Dataset is empty")
    if len(rows) > max_rows:
        raise ValueError(f"Dataset exceeds {max_rows} rows")
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("Every dataset row must be an object")
    return rows
