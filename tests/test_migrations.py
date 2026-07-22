from scripts.verify_migrations import verify


def test_alembic_upgrades_empty_and_old_sqlite_idempotently(tmp_path):
    report = verify(tmp_path)
    assert report["passed"]
    assert report["legacy_upgrade"]
    assert report["empty_upgrade"]
    assert report["repeat_upgrade"]
    assert report["seed_data_preserved"]
    assert report["irreversible"]
