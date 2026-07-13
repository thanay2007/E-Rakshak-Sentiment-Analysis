# SENTINEL — Documentation

Project-level docs that complement the main [README](../README.md).

| Doc | What's inside |
|---|---|
| [FRAMEWORKS.md](FRAMEWORKS.md) | How every framework in the stack is used here (FastAPI, SQLModel, APScheduler, Transformers, Vite, React, Tailwind, GSAP, Recharts, d3-force), with patterns verified against current official docs |
| [diagrams/](diagrams/README.md) | Validated Mermaid diagrams: system architecture, ingestion sequence, ML training pipeline, threat scoring & alert bands, frontend structure — all render natively on GitHub |

## Design file

The UI design source lives in Figma:
**[SENTINEL — Threat Intelligence UI](https://www.figma.com/design/Nq85SNUDDwrPEgPG4AxFtQ)**
(landing screen built with the app's design tokens — base `#0A0E1A`, accent `#14B8C4`,
glass surfaces; extend it page-by-page as the UI evolves).

## Auto-generated wiki (DeepWiki)

[DeepWiki](https://deepwiki.com) can generate a browsable, AI-answerable wiki for the
entire codebase, but it needs to be able to see the repository. This repo is currently
**private**, so:

1. **If you make the repo public**: visit
   <https://deepwiki.com/thanay2007/E-Rakshak-Sentiment-Analysis> once — it indexes the
   repo automatically (takes a few minutes), after which the wiki is browsable and any
   MCP-connected agent can `ask_question` against it.
2. **If it stays private**: DeepWiki's private mode requires a Devin account with the
   GitHub integration installed on this repo (Settings → Integrations at app.devin.ai),
   after which `generate_wiki` becomes available.

Until then, the [main README](../README.md), [FRAMEWORKS.md](FRAMEWORKS.md) and the
[diagrams](diagrams/README.md) are the canonical documentation.
