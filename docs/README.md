# SENTINEL documentation

Public-sentiment monitoring for the Gujarat Police, built for Surat, Ahmedabad,
Vadodara and Rajkot. This folder documents what the system does, how each part
reaches its answer, and — for the parts where that matters most — why it was
built the way it was rather than the obvious way.

Everything here is written against the code as it stands. Where a document
quotes a number (a model's accuracy, a score threshold, a rate limit), that
number came from a report file or a config default in this repository, and the
file it came from is named.

## Start here

| If you want to | Read |
|---|---|
| Understand the system in one pass | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Run it locally | [OPERATIONS.md](OPERATIONS.md) |
| Know where the posts come from | [COLLECTION.md](COLLECTION.md) |
| Follow one post from text to label | [NLP-PIPELINE.md](NLP-PIPELINE.md) |
| Understand the three models | [MODELS.md](MODELS.md) |
| Understand the 0-100 number | [SCORING.md](SCORING.md) |
| See where the LLMs are used | [LLM.md](LLM.md) |
| Understand the voice assistant | [VOICE.md](VOICE.md) |
| Understand faces, images and OSINT | [FORENSICS.md](FORENSICS.md) |
| Check the security posture | [SECURITY.md](SECURITY.md) |
| Put it on a GPU | [GPU.md](GPU.md) |
| Move off SQLite | [SUPABASE.md](SUPABASE.md) |
| Know which libraries are used and why | [FRAMEWORKS.md](FRAMEWORKS.md) |

Diagram sources live in [diagrams/](diagrams/); every document also embeds its
diagrams inline so they render on GitHub without leaving the page.

## The system in six sentences

Collectors read public posts from seven platforms on politeness-gapped
schedules and hand them to one ingestion function. That function de-duplicates,
geo-tags and enriches every post through a single NLP pipeline, which labels it
**positive, negative or neutral** and attaches a **0-100 concern score**. Three
independent sentiment models vote on the label and an LLM reviews the verdict,
so a label is never one model's opinion. Posts, alerts, reports, watchlist edits
and every investigative action land in one append-only-audited database. A React
dashboard reads that database, and an officer can interrogate it by voice. No
part of the system claims a post is a crime — it says how negative the mood is,
how confident it is, and what evidence produced that answer.

## What this system deliberately does not do

* It does not assign threat categories. Labels like "incitement" or "fake news"
  are investigative conclusions no sentiment model can reach from one post, and
  the four-label taxonomy that once existed was removed for that reason. See
  [SCORING.md](SCORING.md).
* It does not fact-check. It corroborates: [LLM.md](LLM.md) explains what the
  news-corroboration tier does and does not assert.
* It does not identify people from a face without saying how sure it is, and it
  will not auto-pull a dossier on a weak match. See [FORENSICS.md](FORENSICS.md).
* It does not drop posts it cannot read. Filtering on language or script at
  collection time is an evasion route, so translation happens after collection,
  never before. See [NLP-PIPELINE.md](NLP-PIPELINE.md).
