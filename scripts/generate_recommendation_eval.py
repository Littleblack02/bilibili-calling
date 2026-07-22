"""Generate a deterministic, deidentified temporal recommendation fixture.

The fixture is synthetic/editorial. It exercises evaluation mechanics and is
not evidence of production uplift on real Bilibili users.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import random

from rdflib import Graph, Namespace, RDF, SKOS, URIRef


ROOT = Path(__file__).resolve().parents[1]
BILI = Namespace("https://bilibili.local/ontology/")
DOMAINS = ("ai", "game", "animation", "music", "film", "knowledge", "life")
CUTOFF = datetime(2026, 6, 1, tzinfo=timezone.utc)
QUALITY_BY_SLOT = (
    0.35, 0.95, 0.50, 0.88, 0.62, 0.75,
    0.42, 0.68, 0.57, 0.73, 0.46, 0.64,
    0.39, 0.70, 0.53, 0.66, 0.44, 0.60,
    0.37, 0.58, 0.49, 0.56, 0.41, 0.54,
)


def _hash(value: str) -> str:
    return hashlib.sha256(("public-synthetic-v2:" + value).encode()).hexdigest()


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _concepts(domain: str) -> list[dict[str, object]]:
    graph = Graph().parse(ROOT / "ontology" / "domains" / f"{domain}.ttl")
    rows: list[dict[str, object]] = []
    for subject in sorted(set(graph.subjects(RDF.type, SKOS.Concept)), key=str):
        if not str(subject).startswith(str(BILI)):
            continue
        labels = list(graph.objects(subject, SKOS.prefLabel))
        if not labels:
            continue
        preferred = next((str(label) for label in labels if label.language == "zh"), str(labels[0]))
        aliases = sorted({str(label) for label in graph.objects(subject, SKOS.altLabel)})
        # Prefer specific concepts. Top-level category nodes are poor test topics.
        if any(True for _ in graph.objects(subject, SKOS.broader)):
            rows.append({"concept_id": str(subject), "topic": preferred, "aliases": aliases})
    if len(rows) < 6:
        raise RuntimeError(f"Ontology module {domain} has fewer than six specific concepts")
    # Stable spread across the module instead of cherry-picking evaluation wins.
    step = max(1, len(rows) // 6)
    selected = [rows[min(index * step, len(rows) - 1)] for index in range(6)]
    return selected


def generate(output_dir: Path, sessions: int = 84, seed: int = 20260721) -> dict[str, object]:
    rng = random.Random(seed)
    concepts = {domain: _concepts(domain) for domain in DOMAINS}
    items: list[dict[str, object]] = []
    by_concept: dict[str, list[dict[str, object]]] = {}
    counter = 1
    for domain in DOMAINS:
        for concept_number, concept in enumerate(concepts[domain]):
            rows = []
            for slot, quality in enumerate(QUALITY_BY_SLOT):
                bvid = f"BVRC{counter:08d}"
                counter += 1
                up_key = f"{domain}-{concept_number}-up-{slot % 3}"
                row = {
                    "schema_version": "1.0",
                    "bvid": bvid,
                    "topic": concept["topic"],
                    "concept_id": concept["concept_id"],
                    "domain": domain,
                    "up_mid_hash": _hash(up_key),
                    "published_at": _iso(CUTOFF - timedelta(days=15 + ((counter * 7) % 70))),
                    "popularity": round(0.2 + ((counter * 37) % 65) / 100, 3),
                    "quality": quality,
                    "recall_source": ("followed_up", "interest", "dynamic_feed", "vector_rediscovery")[slot % 4],
                    "hydrated": True,
                }
                rows.append(row)
                items.append(row)
            by_concept[str(concept["concept_id"])] = rows

    events: list[dict[str, object]] = []
    future_targets = 0

    def add_event(session_hash: str, when: datetime, event_type: str, item: dict[str, object], topic: str) -> None:
        events.append({
            "schema_version": "1.0",
            "session_hash": session_hash,
            "event_time": _iso(when),
            "event_type": event_type,
            "bvid": item["bvid"],
            "topic": topic,
            "up_mid_hash": item["up_mid_hash"],
        })

    for user_index in range(sessions):
        session_hash = _hash(f"session-{user_index}")
        primary_domain_index = user_index % len(DOMAINS)
        primary_domain = DOMAINS[primary_domain_index]
        secondary_domain = DOMAINS[(primary_domain_index + 2 + user_index % 3) % len(DOMAINS)]
        primary = concepts[primary_domain][user_index % 6]
        secondary = concepts[secondary_domain][(user_index * 3 + 1) % 6]
        old = concepts[primary_domain][(user_index + 3) % 6]

        old_rows = by_concept[str(old["concept_id"])]
        primary_rows = by_concept[str(primary["concept_id"])]
        secondary_rows = by_concept[str(secondary["concept_id"])]

        old_count = 3 + user_index % 5
        activity_shift = (0, 12, 35)[user_index % 3]
        for offset in range(old_count):
            add_event(
                session_hash,
                CUTOFF - timedelta(days=210 - offset * 9),
                "favorite",
                old_rows[4 + offset % 2],
                str(old["topic"]),
            )

        # Half of the sessions use an alias; exact-string baselines cannot join
        # it to candidate metadata, while ontology linking can.
        aliases = list(primary["aliases"])
        primary_signal = str(primary["topic"])
        if user_index % 2 and aliases:
            primary_signal = str(aliases[user_index % len(aliases)])
        primary_count = 2 + user_index % 4
        for offset in range(primary_count):
            add_event(
                session_hash,
                CUTOFF - timedelta(days=10 + activity_shift - min(offset * 2, 6)),
                "viewed",
                primary_rows[4 + offset % 2],
                primary_signal,
            )
        add_event(session_hash, CUTOFF - timedelta(days=2 + activity_shift), "like", primary_rows[4], primary_signal)

        secondary_aliases = list(secondary["aliases"])
        secondary_signal = str(secondary_aliases[0]) if secondary_aliases else str(secondary["topic"])
        add_event(session_hash, CUTOFF - timedelta(days=8 + activity_shift), "viewed", secondary_rows[4], secondary_signal)
        add_event(session_hash, CUTOFF - timedelta(days=3 + activity_shift), "watch_later", secondary_rows[5], secondary_signal)
        # A creator-level signal used only by the dynamic/following feature.
        add_event(session_hash, CUTOFF - timedelta(days=1 + activity_shift), "like", primary_rows[5], primary_signal)

        targets = [primary_rows[1], primary_rows[3], secondary_rows[1]]
        if user_index % 3 == 0:
            targets.append(old_rows[1])
        for target_index, target in enumerate(targets):
            add_event(
                session_hash,
                CUTOFF + timedelta(days=2 + target_index * 2),
                "favorite" if target_index == 1 else "viewed",
                target,
                str(target["topic"]),
            )
            future_targets += 1

    # Event order is part of the time-split contract.
    events.sort(key=lambda row: (str(row["event_time"]), str(row["session_hash"]), str(row["bvid"])))
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, rows in (("recommendation_items.jsonl", items), ("recommendation_events.jsonl", events)):
        path = output_dir / filename
        path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")

    lock = {
        "schema_version": "1.0",
        "dataset_kind": "deterministic_synthetic_editorial",
        "seed": seed,
        "cutoff": _iso(CUTOFF),
        "sessions": sessions,
        "items": len(items),
        "events": len(events),
        "future_targets": future_targets,
        "sha256": {
            name: hashlib.sha256((output_dir / name).read_bytes()).hexdigest()
            for name in ("recommendation_items.jsonl", "recommendation_events.jsonl")
        },
        "limitations": "Synthetic regression fixture; does not represent live Bilibili traffic or online causal uplift.",
    }
    (output_dir / "recommendation.lock.json").write_text(
        json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return lock


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "evaluation")
    parser.add_argument("--sessions", type=int, default=84)
    parser.add_argument("--seed", type=int, default=20260721)
    args = parser.parse_args()
    print(json.dumps(generate(args.output_dir, args.sessions, args.seed), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
