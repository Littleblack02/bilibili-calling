from scripts.benchmark_local_performance import benchmark


def test_local_200_candidate_ranking_stays_under_p95_gate():
    report = benchmark(iterations=8, candidates_count=200)
    assert report["passed"]
    assert report["metrics"]["hydrated_candidates"] == 200
