# Diagrams

Mermaid sources, rendered natively by GitHub. Each is also embedded in the
document it belongs to, so you can read the explanation and the picture together
rather than jumping between files.

| Diagram | Source | Explained in |
|---|---|---|
| System architecture | [`system-architecture.mmd`](system-architecture.mmd) | [ARCHITECTURE.md](../ARCHITECTURE.md) |
| Ingestion sequence (tick → dashboard) | [`ingestion-sequence.mmd`](ingestion-sequence.mmd) | [ARCHITECTURE.md](../ARCHITECTURE.md) |
| Account discovery and the roster | [`account-discovery.mmd`](account-discovery.mmd) | [COLLECTION.md](../COLLECTION.md) |
| Three-model sentiment ensemble | [`sentiment-ensemble.mmd`](sentiment-ensemble.mmd) | [MODELS.md](../MODELS.md) |
| Concern score and alert bands | [`concern-scoring.mmd`](concern-scoring.mmd) | [SCORING.md](../SCORING.md) |
| ML training pipeline (`app.ml.bootstrap`) | [`ml-training-pipeline.mmd`](ml-training-pipeline.mmd) | [MODELS.md](../MODELS.md) |
| Voice pipeline | [`voice-pipeline.mmd`](voice-pipeline.mmd) | [VOICE.md](../VOICE.md) |
| Frontend structure | [`frontend-structure.mmd`](frontend-structure.mmd) | [ARCHITECTURE.md](../ARCHITECTURE.md) |

Every source here was rendered through the Mermaid renderer before being
committed, so a diagram that appears in this folder is one that parses.

## Keeping them honest

A diagram that disagrees with the code is worse than no diagram, because it is
believed. Two of these were stale before this pass and both were misleading in
the same way — they still showed the four-label threat taxonomy that was
deliberately removed, and alert bands (74 / 65 / 50) that no post could ever
reach. `threat-scoring.mmd` was replaced by `concern-scoring.mmd` rather than
edited, because the thing it described no longer exists.

When you change one of these, change the numbers in the document too:

| If you change | Update |
|---|---|
| the score weights or bands | `concern-scoring.mmd` + [SCORING.md](../SCORING.md) + `ALERT_THRESHOLD` in `config.py` |
| a model or its weight | `sentiment-ensemble.mmd` + [MODELS.md](../MODELS.md) (the per-language table comes from the report JSONs) |
| a collector or discovery leg | `system-architecture.mmd`, `account-discovery.mmd` + [COLLECTION.md](../COLLECTION.md) |
| the voice engine order | `voice-pipeline.mmd` + [VOICE.md](../VOICE.md) |
