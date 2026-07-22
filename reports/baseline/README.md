# Reproducible V2 baseline

`2026-07-21.json` is the frozen pre-V2 engineering baseline. It records a dirty
worktree explicitly because those changes belong to the user and were preserved.
No environment values, API keys, cookies, database contents or usernames are
included.

The RAG snapshot uses a deterministic in-memory retrieval fixture so every
developer can reproduce expansion and fusion without a real account, network,
embedding API, or mutable Chroma collection. Quality metrics remain `null` until
reviewed gold data exists; passing unit tests is not presented as retrieval or
recommendation quality.

Run the current verification suite with:

```powershell
python -m compileall -q app scripts
python -m pytest -q
python scripts/validate_evaluation_data.py
Set-Location frontend
npm run lint
npm run build
```
