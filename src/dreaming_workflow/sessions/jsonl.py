"""Reading rules both session parsers share."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime

from dreaming_workflow.sessions.model import SessionFile

IMAGE_TEXT = "[image]"
UNKNOWN_PROJECT_DIR = "unknown"

type Record = dict[str, object]


def read_records(file: SessionFile) -> Iterator[Record]:
    """Yield each line that parses as a JSON object; skip the rest, such as a partial last line."""
    with file.path.open("rb") as lines:
        for line in lines:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                yield record


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def as_dict(value: object) -> Record | None:
    if not isinstance(value, dict):
        return None
    # Values come from JSON, whose object keys are always strings.
    record: Record = value
    return record


def as_str(value: object) -> str | None:
    return value if isinstance(value, str) else None
