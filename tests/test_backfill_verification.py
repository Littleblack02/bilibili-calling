from scripts.verify_backfill import verify


def test_ontology_backfill_is_verified_on_disposable_database():
    report = verify()
    assert report["database_scope"] == "disposable_temporary_sqlite"
    assert report["passed"]
