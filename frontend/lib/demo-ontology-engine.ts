import snapshot from "./demo-ontology.json";

export type OntologyStage = "exact_label" | "label_in_text" | "fuzzy_lexical";

export interface BrowserConceptMatch {
  conceptId: string;
  label: string;
  matchedLabel: string;
  conceptType: string;
  confidence: number;
  stage: OntologyStage;
}

export interface BrowserPathEdge {
  from: string;
  relation: string;
  to: string;
}

export interface BrowserExpandedConcept {
  conceptId: string;
  label: string;
  weight: number;
  path: BrowserPathEdge[];
}

type SnapshotConcept = (typeof snapshot.concepts)[number];

const conceptsById = new Map(snapshot.concepts.map((concept) => [concept.id, concept]));
const labelRows = snapshot.concepts.flatMap((concept) => [
  { concept, label: concept.label, preferred: true },
  ...concept.aliases.map((label) => ({ concept, label, preferred: false })),
]);

const adjacency = new Map<string, Array<{ to: string; relation: string; weight: number }>>();

function addEdge(from: string, to: string, relation: string, weight: number) {
  const edges = adjacency.get(from) ?? [];
  edges.push({ to, relation, weight });
  adjacency.set(from, edges);
}

for (const relation of snapshot.relations) {
  if (relation.relation === "broader") {
    addEdge(relation.from, relation.to, "broader", 0.78);
    addEdge(relation.to, relation.from, "narrower", 0.72);
  } else if (relation.relation === "related") {
    addEdge(relation.from, relation.to, "related", 0.52);
    addEdge(relation.to, relation.from, "related", 0.52);
  } else if (relation.relation === "requires") {
    addEdge(relation.from, relation.to, "requires", 0.58);
    addEdge(relation.to, relation.from, "requiredBy", 0.5);
  }
}

export const demoOntologyMeta = {
  version: snapshot.version,
  activeConcepts: snapshot.concepts.length,
  triples: snapshot.tripleCount,
  relations: snapshot.relations.length,
};

export function normalizeOntologyLabel(value: string) {
  return (value || "")
    .normalize("NFKC")
    .toLocaleLowerCase()
    .replace(/[\s\-_/:：·.,，。!！?？()（）\[\]【】'"“”‘’]/g, "");
}

function asciiBoundaryPresent(text: string, label: string) {
  const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(^|[^a-z0-9])${escaped}([^a-z0-9]|$)`, "i").test(text);
}

function levenshtein(left: string, right: string) {
  const previous = Array.from({ length: right.length + 1 }, (_, index) => index);
  for (let leftIndex = 1; leftIndex <= left.length; leftIndex += 1) {
    const current = [leftIndex];
    for (let rightIndex = 1; rightIndex <= right.length; rightIndex += 1) {
      const substitution = previous[rightIndex - 1]
        + (left[leftIndex - 1] === right[rightIndex - 1] ? 0 : 1);
      current[rightIndex] = Math.min(
        previous[rightIndex] + 1,
        current[rightIndex - 1] + 1,
        substitution,
      );
    }
    previous.splice(0, previous.length, ...current);
  }
  return previous[right.length];
}

function fuzzySimilarity(left: string, right: string) {
  if (!left || !right) return 0;
  return 1 - levenshtein(left, right) / Math.max(left.length, right.length);
}

function toMatch(
  concept: SnapshotConcept,
  matchedLabel: string,
  confidence: number,
  stage: OntologyStage,
): BrowserConceptMatch {
  return {
    conceptId: concept.id,
    label: concept.label,
    matchedLabel,
    conceptType: concept.type,
    confidence: Math.round(confidence * 1000) / 1000,
    stage,
  };
}

export function resolveOntologyText(text: string, limit = 6): BrowserConceptMatch[] {
  const original = (text || "").normalize("NFKC");
  const normalizedText = normalizeOntologyLabel(original);
  if (!normalizedText) return [];

  const exact = new Map<string, BrowserConceptMatch>();
  for (const row of labelRows) {
    const normalizedLabel = normalizeOntologyLabel(row.label);
    if (!normalizedLabel) continue;
    const shortAscii = /^[\x00-\x7F]+$/.test(row.label) && normalizedLabel.length <= 12;
    const present = shortAscii
      ? asciiBoundaryPresent(original, row.label)
      : normalizedText.includes(normalizedLabel);
    if (!present) continue;
    const whole = normalizedLabel === normalizedText;
    const confidence = whole
      ? (row.preferred ? 1 : 0.98)
      : (row.preferred ? 0.95 : 0.92);
    const match = toMatch(
      row.concept,
      row.label,
      confidence,
      whole ? "exact_label" : "label_in_text",
    );
    const prior = exact.get(row.concept.id);
    if (!prior || match.confidence > prior.confidence) exact.set(row.concept.id, match);
  }
  if (exact.size) {
    const rows = [...exact.values()].sort((left, right) =>
      normalizeOntologyLabel(right.matchedLabel).length
      - normalizeOntologyLabel(left.matchedLabel).length
      || right.confidence - left.confidence);
    return rows.filter((row, index) => !rows.some((other, otherIndex) =>
      otherIndex < index
      && normalizeOntologyLabel(other.matchedLabel) !== normalizeOntologyLabel(row.matchedLabel)
      && normalizeOntologyLabel(other.matchedLabel).includes(
        normalizeOntologyLabel(row.matchedLabel),
      ))).slice(0, limit);
  }

  const tokens = original.match(/[a-zA-Z0-9+#.\-]{3,}|[\u4e00-\u9fff]{2,}/g) ?? [original];
  const fuzzy = new Map<string, BrowserConceptMatch>();
  for (const row of labelRows) {
    const normalizedLabel = normalizeOntologyLabel(row.label);
    if (normalizedLabel.length < 4) continue;
    const best = Math.max(...tokens.map((token) =>
      fuzzySimilarity(normalizeOntologyLabel(token), normalizedLabel)));
    if (best < 0.72) continue;
    const match = toMatch(row.concept, row.label, 0.58 + 0.38 * best, "fuzzy_lexical");
    const prior = fuzzy.get(row.concept.id);
    if (!prior || match.confidence > prior.confidence) fuzzy.set(row.concept.id, match);
  }
  const ranked = [...fuzzy.values()].sort((left, right) => right.confidence - left.confidence);
  if (ranked.length > 1 && ranked[0].confidence - ranked[1].confidence < 0.04) return [];
  return ranked.slice(0, 1);
}

export function expandOntologyConcepts(
  conceptIds: string[],
  maxHops = 2,
): BrowserExpandedConcept[] {
  const best = new Map<string, BrowserExpandedConcept>();
  const queue: Array<{ id: string; hops: number; weight: number; path: BrowserPathEdge[] }> = [];
  for (const conceptId of conceptIds) {
    const concept = conceptsById.get(conceptId);
    if (!concept) continue;
    const row = { conceptId, label: concept.label, weight: 1, path: [] };
    best.set(conceptId, row);
    queue.push({ id: conceptId, hops: 0, weight: 1, path: [] });
  }
  while (queue.length) {
    const current = queue.shift();
    if (!current || current.hops >= maxHops) continue;
    const source = conceptsById.get(current.id);
    if (!source) continue;
    for (const edge of adjacency.get(current.id) ?? []) {
      const target = conceptsById.get(edge.to);
      if (!target) continue;
      const weight = current.weight * edge.weight;
      if (weight < 0.2 || weight <= (best.get(edge.to)?.weight ?? 0)) continue;
      const path = [...current.path, {
        from: source.label,
        relation: edge.relation,
        to: target.label,
      }];
      best.set(edge.to, {
        conceptId: edge.to,
        label: target.label,
        weight: Math.round(weight * 1000) / 1000,
        path,
      });
      queue.push({ id: edge.to, hops: current.hops + 1, weight, path });
    }
  }
  return [...best.values()].sort((left, right) => right.weight - left.weight).slice(0, 12);
}
