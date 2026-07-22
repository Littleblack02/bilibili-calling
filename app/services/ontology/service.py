"""Standards-based, deterministic ontology service.

The service deliberately keeps ontology reasoning independent from the LLM.  It
uses SKOS labels and relations for entity linking and bounded graph expansion,
which makes retrieval/ranking behavior reproducible and testable.
"""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import re
import unicodedata
from typing import Any, Iterable

from rdflib import Graph, Literal, Namespace, RDF, RDFS, SKOS, URIRef
from rdflib.namespace import DCTERMS, OWL

from app.config import settings
from app.services.observability import metrics
from app.services.ontology.entity_linker import EntityLinker


BILI = Namespace("https://bilibili.local/ontology/")


@dataclass(frozen=True)
class ConceptMatch:
    concept_id: str
    label: str
    concept_type: str
    matched_label: str
    confidence: float
    source: str = "ontology_label"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OntologyAnnotation:
    concept_id: str
    label: str
    concept_type: str
    relation_type: str
    confidence: float
    evidence_text: str
    source: str = "deterministic_entity_linker"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class OntologyService:
    _RELATION_WEIGHTS = {
        str(SKOS.broader): 0.78,
        str(SKOS.narrower): 0.72,
        str(SKOS.related): 0.52,
        str(BILI.requires): 0.58,
    }

    def __init__(
        self,
        ontology_path: str | Path | None = None,
        shapes_path: str | Path | None = None,
    ) -> None:
        project_root = Path(__file__).resolve().parents[3]
        self.ontology_path = Path(ontology_path) if ontology_path else None
        self.manifest_path = project_root / "ontology" / "manifest.json"
        self.shapes_path = Path(shapes_path or project_root / "ontology" / "shapes.ttl")
        self.graph = Graph()
        self.module_paths: list[Path] = []
        if self.ontology_path:
            self.module_paths = [self.ontology_path]
        else:
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            ontology_root = self.manifest_path.parent
            self.module_paths = [ontology_root / item for item in manifest["modules"]]
            if any("personal" in {part.casefold() for part in path.parts} for path in self.module_paths):
                raise ValueError("Public ontology manifest must not load personal concept modules")
        for module_path in self.module_paths:
            self.graph.parse(module_path, format="turtle")
        version_values = {
            str(version)
            for ontology_node in self.graph.subjects(RDF.type, OWL.Ontology)
            for version in self.graph.objects(ontology_node, OWL.versionInfo)
        }
        if len(version_values) != 1:
            raise ValueError(
                "Public ontology must declare exactly one owl:versionInfo value"
            )
        self.VERSION = f"bili-ontology-{version_values.pop()}"
        self._label_index: dict[str, list[tuple[URIRef, str, bool]]] = {}
        self._preferred_labels: dict[URIRef, str] = {}
        self._alternate_labels: dict[URIRef, list[str]] = {}
        self._types: dict[URIRef, str] = {}
        self._adjacency: dict[URIRef, list[tuple[URIRef, str, float]]] = {}
        self._build_indexes()
        self.entity_linker = EntityLinker(
            self.list_concepts(),
            normalize=self.normalize_label,
            accept_threshold=settings.ontology_linker_accept_threshold,
            ambiguity_margin=settings.ontology_linker_ambiguity_margin,
        )

    @staticmethod
    def normalize_label(value: str) -> str:
        value = unicodedata.normalize("NFKC", value or "").casefold()
        return re.sub(r"[\s\-_/:：·,.，。!?！？()（）\[\]【】]+", "", value)

    @staticmethod
    def _local_name(uri: URIRef) -> str:
        text = str(uri)
        return text.rsplit("/", 1)[-1].rsplit("#", 1)[-1]

    def _concept_type(self, concept: URIRef) -> str:
        for class_uri, name in (
            (BILI.Skill, "skill"),
            (BILI.ContentFormat, "format"),
            (BILI.Difficulty, "difficulty"),
            (BILI.Category, "category"),
            (BILI.PersonalConcept, "personal"),
            (BILI.Topic, "topic"),
        ):
            if (concept, RDF.type, class_uri) in self.graph:
                return name
        return "concept"

    def _build_indexes(self) -> None:
        concepts = set(self.graph.subjects(RDF.type, SKOS.Concept))
        concepts.update(self.graph.subjects(SKOS.prefLabel, None))
        for concept in concepts:
            if not isinstance(concept, URIRef):
                continue
            preferred = [str(label) for label in self.graph.objects(concept, SKOS.prefLabel)]
            alternates = [str(label) for label in self.graph.objects(concept, SKOS.altLabel)]
            if not preferred:
                continue
            zh_label = next(
                (str(label) for label in self.graph.objects(concept, SKOS.prefLabel)
                 if isinstance(label, Literal) and label.language == "zh"),
                preferred[0],
            )
            self._preferred_labels[concept] = zh_label
            self._alternate_labels[concept] = alternates
            self._types[concept] = self._concept_type(concept)
            for label in preferred:
                normalized = self.normalize_label(label)
                if normalized:
                    self._label_index.setdefault(normalized, []).append((concept, label, True))
            for label in alternates:
                normalized = self.normalize_label(label)
                if normalized:
                    self._label_index.setdefault(normalized, []).append((concept, label, False))

        for subject in self._preferred_labels:
            links: list[tuple[URIRef, str, float]] = []
            for predicate, default_weight in (
                (SKOS.broader, 0.78),
                (SKOS.narrower, 0.72),
                (SKOS.related, 0.52),
                (BILI.requires, 0.58),
            ):
                for target in self.graph.objects(subject, predicate):
                    if isinstance(target, URIRef) and target in self._preferred_labels:
                        links.append((target, self._local_name(predicate), default_weight))
            # Treat broader/narrower and requires as navigable in both directions,
            # but slightly discount the inferred inverse edge.
            for source in self.graph.subjects(SKOS.broader, subject):
                if isinstance(source, URIRef) and source in self._preferred_labels:
                    links.append((source, "narrower", 0.72))
            for source in self.graph.subjects(BILI.requires, subject):
                if isinstance(source, URIRef) and source in self._preferred_labels:
                    links.append((source, "requiredBy", 0.50))
            self._adjacency[subject] = links

    def concept(self, concept_id: str) -> dict[str, Any] | None:
        uri = URIRef(concept_id)
        label = self._preferred_labels.get(uri)
        if not label:
            return None
        definitions = [str(value) for value in self.graph.objects(uri, SKOS.definition)]
        sources = [str(value) for value in self.graph.objects(uri, DCTERMS.source)]
        replacements = [str(value) for value in self.graph.objects(uri, DCTERMS.isReplacedBy)]
        tid = next(iter(self.graph.objects(uri, BILI.bilibiliTid)), None)
        return {
            "concept_id": concept_id,
            "label": label,
            "concept_type": self._types.get(uri, "concept"),
            "aliases": list(self._alternate_labels.get(uri, [])),
            "definition": definitions[0] if definitions else None,
            "source": sources[0] if sources else None,
            "status": str(next(iter(self.graph.objects(uri, BILI.status)), "")) or None,
            "maintenance_version": str(
                next(iter(self.graph.objects(uri, BILI.maintenanceVersion)), "")
            ) or None,
            "deprecated": bool(next(iter(self.graph.objects(uri, OWL.deprecated)), False)),
            "replaced_by": replacements,
            "bilibili_tid": int(tid) if tid is not None else None,
        }

    def list_concepts(self, concept_type: str | None = None) -> list[dict[str, Any]]:
        rows = [self.concept(str(uri)) for uri in self._preferred_labels]
        rows = [row for row in rows if row]
        if concept_type:
            rows = [row for row in rows if row["concept_type"] == concept_type]
        return sorted(rows, key=lambda row: (row["concept_type"], row["label"]))

    @staticmethod
    def _ascii_label_present(text: str, label: str) -> bool:
        escaped = re.escape(label.casefold())
        return bool(re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", text.casefold()))

    def resolve_text(self, text: str, limit: int = 12) -> list[ConceptMatch]:
        """Resolve text to canonical concepts using preferred/alternative labels.

        Longest labels win and duplicate concepts are collapsed. Short ASCII
        aliases such as AI/ML require token boundaries to avoid false matches.
        """
        if settings.ontology_linker_v2_enabled:
            result = self.link_text_v2(text, limit=limit)
            return [ConceptMatch(
                concept_id=row["concept_id"],
                label=row["label"],
                concept_type=row["concept_type"],
                matched_label=row["matched_label"],
                confidence=row["confidence"],
                source=f"entity_linker_v2:{row['stage']}",
            ) for row in result["selected"]]

        original = unicodedata.normalize("NFKC", text or "")
        normalized_text = self.normalize_label(original)
        if not normalized_text:
            return []

        candidates: list[tuple[int, float, URIRef, str, bool]] = []
        for normalized_label, entries in self._label_index.items():
            if not normalized_label:
                continue
            for concept, matched_label, preferred in entries:
                ascii_only = bool(re.fullmatch(r"[A-Za-z0-9 .+\-]+", matched_label))
                if ascii_only and len(normalized_label) <= 3:
                    present = self._ascii_label_present(original, matched_label)
                else:
                    present = normalized_label in normalized_text
                if not present:
                    continue
                exact = normalized_label == normalized_text
                confidence = 1.0 if exact and preferred else 0.98 if exact else 0.94 if preferred else 0.90
                candidates.append((len(normalized_label), confidence, concept, matched_label, preferred))

        candidates.sort(key=lambda row: (row[0], row[1]), reverse=True)
        seen: set[URIRef] = set()
        results: list[ConceptMatch] = []
        for _, confidence, concept, matched_label, _ in candidates:
            if concept in seen:
                continue
            seen.add(concept)
            results.append(ConceptMatch(
                concept_id=str(concept),
                label=self._preferred_labels[concept],
                concept_type=self._types.get(concept, "concept"),
                matched_label=matched_label,
                confidence=round(confidence, 4),
            ))
            if len(results) >= limit:
                break
        return results

    def link_text_v2(
        self,
        text: str,
        *,
        context: dict[str, Any] | None = None,
        limit: int = 12,
    ) -> dict[str, Any]:
        """Return candidates, selections, confidence and explicit rejection."""
        result = self.entity_linker.link(text, context=context, limit=limit)
        metrics.inc("entity_linking_requests_total")
        metrics.inc(
            "entity_linking_outcomes_total",
            outcome="linked" if result.get("selected") else "rejected",
            reason=result.get("rejection_reason") or "selected",
        )
        metrics.observe("entity_linking_selected_concepts", len(result.get("selected") or []))
        if str(result.get("rejection_reason") or "").startswith("ambiguous"):
            metrics.inc("entity_linking_ambiguity_total")
        return result

    def annotate_video(self, title: str, content: str = "", limit: int = 20) -> list[OntologyAnnotation]:
        title_matches = self.resolve_text(title, limit=limit)
        body_matches = self.resolve_text((content or "")[:12000], limit=limit)
        merged: dict[str, ConceptMatch] = {}
        evidence: dict[str, str] = {}
        for match in title_matches:
            merged[match.concept_id] = match
            evidence[match.concept_id] = title[:500]
        for match in body_matches:
            prior = merged.get(match.concept_id)
            adjusted = ConceptMatch(**{
                **match.as_dict(),
                "confidence": round(match.confidence * 0.90, 4),
            })
            if prior is None or adjusted.confidence > prior.confidence:
                merged[match.concept_id] = adjusted
                evidence[match.concept_id] = match.matched_label

        relation_by_type = {
            "skill": "teaches",
            "format": "has_format",
            "difficulty": "has_difficulty",
            "topic": "about_topic",
            "category": "about_topic",
            "concept": "about_topic",
        }
        annotations = [OntologyAnnotation(
            concept_id=match.concept_id,
            label=match.label,
            concept_type=match.concept_type,
            relation_type=relation_by_type.get(match.concept_type, "about_topic"),
            confidence=match.confidence,
            evidence_text=evidence.get(match.concept_id, match.matched_label)[:500],
        ) for match in merged.values()]
        output = sorted(annotations, key=lambda row: row.confidence, reverse=True)[:limit]
        metrics.observe("ontology_concepts_per_video", len(output))
        return output

    def expand_concepts(
        self,
        concept_ids: Iterable[str],
        max_hops: int = 2,
        min_weight: float = 0.20,
    ) -> list[dict[str, Any]]:
        best: dict[URIRef, tuple[float, list[dict[str, str]]]] = {}
        queue: deque[tuple[URIRef, int, float, list[dict[str, str]]]] = deque()
        for concept_id in concept_ids:
            uri = URIRef(concept_id)
            if uri not in self._preferred_labels:
                continue
            best[uri] = (1.0, [])
            queue.append((uri, 0, 1.0, []))

        while queue:
            current, hops, weight, path = queue.popleft()
            if hops >= max_hops:
                continue
            for target, relation, edge_weight in self._adjacency.get(current, []):
                next_weight = weight * edge_weight
                if next_weight < min_weight:
                    continue
                edge = {
                    "from": self._preferred_labels[current],
                    "relation": relation,
                    "to": self._preferred_labels[target],
                }
                next_path = [*path, edge]
                if next_weight <= best.get(target, (0.0, []))[0]:
                    continue
                best[target] = (next_weight, next_path)
                queue.append((target, hops + 1, next_weight, next_path))

        return sorted(({
            "concept_id": str(uri),
            "label": self._preferred_labels[uri],
            "concept_type": self._types.get(uri, "concept"),
            "weight": round(weight, 4),
            "path": path,
        } for uri, (weight, path) in best.items()), key=lambda row: row["weight"], reverse=True)

    def expand_query(self, query: str, max_terms: int = 6) -> list[dict[str, Any]]:
        matches = self.resolve_text(query, limit=5)
        if not matches:
            return [{"query": query, "weight": 1.0, "concept_id": None, "path": []}]
        expanded = self.expand_concepts([match.concept_id for match in matches], max_hops=1)
        results = [{"query": query, "weight": 1.0, "concept_id": None, "path": []}]
        seen = {self.normalize_label(query)}
        for row in expanded:
            candidates = [row["label"], *self._alternate_labels.get(URIRef(row["concept_id"]), [])]
            for label in candidates:
                normalized = self.normalize_label(label)
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                results.append({
                    "query": label,
                    "weight": row["weight"],
                    "concept_id": row["concept_id"],
                    "path": row["path"],
                })
                break
            if len(results) >= max_terms:
                break
        return results

    def descendants(
        self, concept_ids: Iterable[str], max_hops: int = 3
    ) -> set[str]:
        """Return exact concepts and SKOS descendants only.

        This directional traversal is intentionally separate from semantic
        retrieval expansion: blocking a narrow topic must not block its broad
        parent or unrelated siblings.
        """
        found: set[URIRef] = set()
        queue: deque[tuple[URIRef, int]] = deque()
        for concept_id in concept_ids:
            uri = URIRef(concept_id)
            if uri in self._preferred_labels and uri not in found:
                found.add(uri)
                queue.append((uri, 0))
        while queue:
            current, hops = queue.popleft()
            if hops >= max_hops:
                continue
            for child in self.graph.subjects(SKOS.broader, current):
                if isinstance(child, URIRef) and child in self._preferred_labels and child not in found:
                    found.add(child)
                    queue.append((child, hops + 1))
        return {str(uri) for uri in found}

    def ancestors(
        self, concept_ids: Iterable[str], max_hops: int = 2
    ) -> dict[str, float]:
        """Return exact concepts and broader ancestors with weak hop decay."""
        found: dict[URIRef, float] = {}
        queue: deque[tuple[URIRef, int, float]] = deque()
        for concept_id in concept_ids:
            uri = URIRef(concept_id)
            if uri in self._preferred_labels:
                found[uri] = 1.0
                queue.append((uri, 0, 1.0))
        while queue:
            current, hops, weight = queue.popleft()
            if hops >= max_hops:
                continue
            for parent in self.graph.objects(current, SKOS.broader):
                if not isinstance(parent, URIRef) or parent not in self._preferred_labels:
                    continue
                next_weight = weight * 0.20
                if next_weight <= found.get(parent, 0.0):
                    continue
                found[parent] = next_weight
                queue.append((parent, hops + 1, next_weight))
        return {str(uri): round(weight, 6) for uri, weight in found.items()}

    def semantic_match(
        self,
        candidate_text: str,
        affinities: dict[str, float],
        max_hops: int = 2,
    ) -> tuple[float, list[dict[str, Any]], list[dict[str, str]]]:
        candidate_matches = self.resolve_text(candidate_text, limit=12)
        affinity_index = self.build_semantic_index(affinities, max_hops=max_hops)
        return self.semantic_match_concepts(candidate_matches, affinity_index)

    def build_semantic_index(
        self,
        affinities: dict[str, float],
        max_hops: int = 2,
    ) -> dict[str, list[dict[str, Any]]]:
        """Pre-expand one profile affinity map for a batch of candidates.

        Ranking normally evaluates hundreds of already-hydrated videos against
        the same handful of profile affinity maps.  Building this reverse index
        once changes that hot path from repeated graph traversals to bounded
        concept-id lookups while retaining the exact relation paths used for
        explanations.
        """
        index: dict[str, list[dict[str, Any]]] = {}
        for interest_id, affinity in (affinities or {}).items():
            try:
                affinity_value = max(0.0, min(1.0, float(affinity)))
            except (TypeError, ValueError):
                continue
            if affinity_value <= 0:
                continue
            for relation in self.expand_concepts([interest_id], max_hops=max_hops):
                concept_id = str(relation["concept_id"])
                index.setdefault(concept_id, []).append({
                    "interest_concept_id": str(interest_id),
                    "score": affinity_value * float(relation["weight"]),
                    "path": relation["path"],
                })
        return index

    def semantic_match_concepts(
        self,
        candidate_concepts: Iterable[ConceptMatch | dict[str, Any] | str],
        affinity_index: dict[str, list[dict[str, Any]]],
    ) -> tuple[float, list[dict[str, Any]], list[dict[str, str]]]:
        """Match prelinked candidate concepts against a prepared profile index."""
        if not affinity_index:
            return 0.0, [], []

        best_score = 0.0
        best_path: list[dict[str, str]] = []
        matched: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for candidate in candidate_concepts:
            if isinstance(candidate, ConceptMatch):
                candidate_id = candidate.concept_id
                label = candidate.label
                confidence = candidate.confidence
            elif isinstance(candidate, dict):
                candidate_id = str(candidate.get("concept_id") or "")
                label = str(candidate.get("label") or "")
                try:
                    confidence = float(candidate.get("confidence", 1.0))
                except (TypeError, ValueError):
                    confidence = 1.0
            else:
                candidate_id = str(candidate)
                label = ""
                confidence = 1.0
            if not candidate_id:
                continue
            confidence = max(0.0, min(1.0, confidence))
            if not label:
                label = self._preferred_labels.get(URIRef(candidate_id), candidate_id)
            for relation in affinity_index.get(candidate_id, []):
                interest_id = str(relation["interest_concept_id"])
                identity = (candidate_id, interest_id)
                if identity in seen:
                    continue
                seen.add(identity)
                try:
                    score = float(relation["score"]) * confidence
                except (TypeError, ValueError):
                    continue
                matched.append({
                    "concept_id": candidate_id,
                    "label": label,
                    "score": round(score, 4),
                    "interest_concept_id": interest_id,
                })
                if score > best_score:
                    best_score = score
                    best_path = relation["path"]
        matched.sort(key=lambda row: row["score"], reverse=True)
        return round(min(1.0, best_score), 4), matched[:5], best_path

    def top_cluster(
        self, concept_id: str, max_hops: int | None = None
    ) -> dict[str, str] | None:
        """Return a broader cluster, optionally stopping at an intermediate level.

        ``max_hops=None`` preserves the V1 root-cluster behavior. V2 passes a
        small explicit bound so LangGraph/Python remain AI-Agent/Programming
        interests instead of both collapsing into Technology.
        """
        uri = URIRef(concept_id)
        if uri not in self._preferred_labels:
            return None
        current = uri
        visited = {current}
        hops = 0
        while max_hops is None or hops < max(0, max_hops):
            parents = [target for target in self.graph.objects(current, SKOS.broader)
                       if isinstance(target, URIRef) and target in self._preferred_labels]
            if not parents:
                break
            parent = parents[0]
            if parent in visited:
                break
            visited.add(parent)
            current = parent
            hops += 1
        return {"concept_id": str(current), "label": self._preferred_labels[current]}

    def validate_graph(self, graph: Graph) -> dict[str, Any]:
        try:
            from pyshacl import validate
            conforms, _, results_text = validate(
                graph,
                shacl_graph=str(self.shapes_path),
                inference="rdfs",
                abort_on_first=False,
            )
            return {
                "conforms": bool(conforms),
                "results": results_text,
                "concept_count": len(set(graph.subjects(RDF.type, SKOS.Concept))),
                "triple_count": len(graph),
                "version": self.VERSION,
                "modules": [str(path) for path in self.module_paths],
            }
        except Exception as exc:
            return {
                "conforms": False,
                "results": str(exc),
                "concept_count": len(set(graph.subjects(RDF.type, SKOS.Concept))),
                "triple_count": len(graph),
                "version": self.VERSION,
                "modules": [str(path) for path in self.module_paths],
            }

    def validate(self) -> dict[str, Any]:
        return self.validate_graph(self.graph)


_ontology_service: OntologyService | None = None


def get_ontology_service() -> OntologyService:
    global _ontology_service
    if _ontology_service is None:
        _ontology_service = OntologyService()
    return _ontology_service
