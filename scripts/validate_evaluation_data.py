"""Validate every versioned, deidentified JSONL evaluation fixture."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Type

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import BaseModel, ValidationError

from app.evaluation.schemas import (
    EntityLinkingExample,
    RagQaExample,
    RagChunkExample,
    RecommendationEventExample,
    RecommendationItemExample,
    validate_public_record,
)


FILES: dict[str, Type[BaseModel]] = {
    "entity_linking.jsonl": EntityLinkingExample,
    "rag_qa.jsonl": RagQaExample,
    "rag_chunks.jsonl": RagChunkExample,
    "recommendation_events.jsonl": RecommendationEventExample,
    "recommendation_items.jsonl": RecommendationItemExample,
}


def validate_directory(directory: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    errors: list[str] = []
    for filename, schema in FILES.items():
        path = directory / filename
        if not path.is_file():
            errors.append(f"{filename}: missing")
            continue
        count = 0
        with path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                    validate_public_record(raw)
                    schema.model_validate(raw)
                    count += 1
                except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                    errors.append(f"{filename}:{line_number}: {exc}")
        counts[filename] = count
    if errors:
        raise ValueError("Evaluation validation failed:\n" + "\n".join(errors))
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=Path, default=Path("evaluation"))
    args = parser.parse_args()
    counts = validate_directory(args.directory)
    print(json.dumps(counts, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
