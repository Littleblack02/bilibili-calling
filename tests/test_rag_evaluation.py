from scripts.evaluate_rag import evaluate
from scripts.generate_rag_eval import generate
from app.evaluation.schemas import RagQaExample


def test_rag_gold_fixture_count_lock_and_contract(tmp_path):
    first = generate(tmp_path)
    first_qa = (tmp_path / "rag_qa.jsonl").read_bytes()
    second = generate(tmp_path)
    assert first["sha256"] == second["sha256"]
    assert first_qa == (tmp_path / "rag_qa.jsonl").read_bytes()
    assert first["questions"] == 150
    assert first["answerable"] == 126
    assert first["unanswerable"] == 24
    assert sum(
        1 for line in (tmp_path / "rag_qa.jsonl").read_text(encoding="utf-8").splitlines()
        if RagQaExample.model_validate_json(line)
    ) == 150


def test_grounded_rag_synthetic_gate_and_latency(tmp_path):
    generate(tmp_path)
    report = evaluate(tmp_path, benchmark_chunks=10000)
    assert report["passed"]
    assert report["dataset"]["benchmark_chunks"] == 10000
    assert report["metrics"]["unanswerable_refusal_rate"] >= 0.90
    assert report["metrics"]["retrieval_latency_p95_ms"] <= 800
