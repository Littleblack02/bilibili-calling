from app.services.ontology import get_ontology_service
from rdflib import Graph, RDF
from rdflib.namespace import OWL
from app.config import settings


AI = "https://bilibili.local/ontology/ArtificialIntelligence"
LLM = "https://bilibili.local/ontology/LargeLanguageModel"
RAG = "https://bilibili.local/ontology/RAG"
TECH = "https://bilibili.local/ontology/Technology"


def test_ontology_conforms_and_resolves_aliases_without_ascii_false_positive():
    ontology = get_ontology_service()
    assert ontology.validate()["conforms"] is True
    assert any(match.concept_id == RAG for match in ontology.resolve_text("RAG 知识库问答"))
    assert any(match.concept_id == LLM for match in ontology.resolve_text("LLM 入门"))
    assert not any(match.concept_id == AI for match in ontology.resolve_text("train station"))


def test_semantic_match_returns_auditable_path():
    score, concepts, path = get_ontology_service().semantic_match(
        "大语言模型教程", {AI: 1.0}, max_hops=2
    )
    assert score > 0
    assert concepts[0]["concept_id"] == LLM
    assert path


def test_blocking_expansion_is_directional():
    ontology = get_ontology_service()
    ai_descendants = ontology.descendants([AI])
    rag_descendants = ontology.descendants([RAG])
    assert RAG in ai_descendants
    assert TECH not in ai_descendants
    assert AI not in rag_descendants


def test_v2_manifest_has_review_metadata_tid_mapping_and_personal_isolation():
    ontology = get_ontology_service()
    report = ontology.validate()
    assert report["version"] == "bili-ontology-2.0.0"
    assert ontology.VERSION.endswith(str(next(
        ontology.graph.objects(
            next(ontology.graph.subjects(RDF.type, OWL.Ontology)), OWL.versionInfo
        )
    )))
    assert 200 <= report["concept_count"] <= 400
    assert len(report["modules"]) == 9
    assert not any("personal" in path.lower() for path in report["modules"])
    for concept in ontology.list_concepts():
        assert concept["definition"]
        assert concept["source"]
        assert concept["status"] in {"active", "deprecated", "draft"}
        assert concept["maintenance_version"] == "2.0.0"
    knowledge = ontology.concept("https://bilibili.local/ontology/Knowledge")
    assert knowledge["bilibili_tid"] == 36


def test_shacl_rejects_cycles_self_links_alias_conflicts_and_bad_deprecation():
    graph = Graph()
    graph.parse(data="""
        @prefix bili: <https://bilibili.local/ontology/> .
        @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
        @prefix dcterms: <http://purl.org/dc/terms/> .
        bili:A a bili:Topic, skos:Concept ; skos:prefLabel "重复"@zh ;
          skos:definition "A"@zh ; dcterms:source "test" ; bili:status "active" ;
          bili:maintenanceVersion "2.0.0" ; skos:broader bili:B ; skos:related bili:A .
        bili:B a bili:Topic, skos:Concept ; skos:prefLabel "重复"@zh ;
          skos:definition "B"@zh ; dcterms:source "test" ; bili:status "deprecated" ;
          bili:maintenanceVersion "2.0.0" ; skos:broader bili:A .
    """, format="turtle")
    result = get_ontology_service().validate_graph(graph)
    assert result["conforms"] is False
    assert "cyclic" in result["results"] or "acyclic" in result["results"]


def test_entity_linker_v2_cascades_fuzzy_context_and_rejection(monkeypatch):
    ontology = get_ontology_service()
    direct = ontology.link_text_v2("LangGraph Agent 工作流")
    direct_ids = {row["concept_id"] for row in direct["selected"]}
    assert "https://bilibili.local/ontology/LangGraph" in direct_ids
    assert "https://bilibili.local/ontology/Agent" in direct_ids
    assert direct["rejected"] is False

    typo = ontology.link_text_v2("LangGraff 智能体工作流")
    assert typo["selected"]
    assert typo["selected"][0]["concept_id"] in {
        "https://bilibili.local/ontology/LangGraph",
        "https://bilibili.local/ontology/Agent",
    }
    assert typo["candidates"]

    for ambiguous in ("Agent", "Java", "Ontology"):
        result = ontology.link_text_v2(ambiguous)
        assert result["rejected"] is True
        assert result["rejection_reason"] == "ambiguous_label_without_context"

    java = ontology.link_text_v2("Java Spring 后端开发教程")
    assert "https://bilibili.local/ontology/Java" in {
        row["concept_id"] for row in java["selected"]
    }
    unknown = ontology.link_text_v2("完全无关的随机字符串 xyzqv")
    assert unknown["rejected"] is True

    monkeypatch.setattr(settings, "ontology_linker_v2_enabled", True)
    matches = ontology.resolve_text("RAG 知识库问答")
    assert any(match.concept_id == RAG and "entity_linker_v2" in match.source for match in matches)
