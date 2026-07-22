# Ontology V2

Ontology V2 is loaded from `ontology/manifest.json`; the legacy
`ontology/bilibili.ttl` remains only as a V1 rollback artifact and is not part
of the V2 public graph. The manifest loads, in order:

- `core.ttl`
- `bilibili-taxonomy.ttl`
- `domains/ai.ttl`
- `domains/game.ttl`
- `domains/animation.ttl`
- `domains/music.ttl`
- `domains/film.ttl`
- `domains/knowledge.ttl`
- `domains/life.ttl`

The runtime ontology version is read from the graph's single
`owl:versionInfo` declaration. Loading fails if the public modules contain no
version or conflicting versions, so Python cannot silently drift from RDF.

The catalog contains 234 editorial concepts and 2,199 RDF triples. Every
concept has a preferred label, definition, provenance source, lifecycle status
and maintenance version. Public Bilibili categories carry an auditable tid
mapping. Deprecated concepts use `owl:deprecated` plus
`dcterms:isReplacedBy`.

Personal concepts are not files in the public manifest. They must use the
`PersonalConcept` class in a per-user store; the manifest loader rejects paths
named `personal`, and SHACL rejects personal concepts in the public graph.

## Entity-linking cascade

`resolve_text` uses the V2 cascade by default. Set
`ONTOLOGY_LINKER_V2_ENABLED=false` to use the deterministic V1 linker instead:

1. exact preferred/alternative labels;
2. token overlap plus RapidFuzz candidate generation;
3. deterministic character-ngram vector candidates (available without remote
   APIs; a future embedding provider can replace this stage without changing
   the result contract);
4. title/context hints for ambiguous labels;
5. confidence threshold, margin check and explicit rejection.

`link_text_v2` returns top candidates, per-stage score components, selections,
confidence, stage and rejection reason. Standalone `Agent`, `Java` and
`Ontology` are rejected without technical context. Longest-match suppression
prevents a specific phrase such as “影视剪辑” from also producing the broad
substring “影视”. The V1 resolver remains available by disabling the flag.

## SHACL and graph quality

SHACL V2 checks required metadata, relation ranges, self-links, broader cycles,
deprecated replacements, exact label conflicts, category tid datatypes and
public/personal separation. `scripts/check_ontology_quality.py` additionally
checks normalized label collisions, duplicate tids and dangling relations.

The locked entity-linking set contains preferred-label, alias, typo/fuzzy and
explicit abstention cases across seven domains. Its SHA-256 and split counts are
stored in `evaluation/entity_linking.lock.json`. Run:

```bash
python scripts/generate_ontology_v2.py
python scripts/check_ontology_quality.py
python scripts/validate_evaluation_data.py
python scripts/evaluate_entity_linking.py --split test
```

The generated fixture is synthetic/editorially derived, so its report proves
deterministic regression quality, not live-query distribution quality. New
real-world reviewed examples should be appended under a new lock version rather
than silently changing the existing test split.
