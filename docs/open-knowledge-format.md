# Scribe & the Open Knowledge Format (OKF)

Scribe stores the knowledge it distills from your sessions in the
[Open Knowledge Format](https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing/) —
an open, vendor-neutral standard for representing curated knowledge as plain
markdown. The point: your knowledge is **just files in your git repo**, readable
by you and by any agent, with no proprietary database, runtime, or SDK in the
way.

## How the wiki maps to OKF

`scribe wiki distill` turns session transcripts into a knowledge base under
`<workspace>/WIKI/`:

```
WIKI/
├── index.md          # navigation — auto-generated from the pages
├── log.md            # chronological history of what was distilled
└── pages/
    ├── deadlock.md
    ├── gbnf-tool-calls.md
    └── ...
```

Every page is a markdown file with an OKF frontmatter block, then human content:

```markdown
---
type: insight          # or: decision, fact, design, preference, question
title: Deadlock fix
description: Why the async distill loop hung and how it was resolved.
tags: [async, bug]
timestamp: 2026-06-15
source: sesija a1b2c
---

# Deadlock fix

The headless distill loop hung because ... (sesija a1b2c, tag a1b2c).
Related: [GBNF tool calls](gbnf-tool-calls.md).
```

This follows OKF v0.1 directly:

- **File path = concept identity.** One page per topic, kebab-case name.
- **Frontmatter = queryable structure.** Only `type` is required; the rest are
  conventions Scribe fills in. Fields: `type, title, description, tags,
  timestamp, source`.
- **Markdown links = the graph.** Pages link to each other to relate concepts.
- **`index.md` / `log.md`** are navigation and history — maintained
  automatically, never hand-edited (the model is told not to touch them).

Scribe also **backfills** frontmatter: if the model writes a bare `# Title`
page, the distiller adds a valid OKF block (inferring `source` from the
`sesija <id>` markers in the body), so the whole wiki stays OKF-compliant
regardless of which local model produced it.

## Source of truth vs. derived indexes

OKF separates the **producer** of knowledge from its **consumers**. Scribe is
built the same way:

| Layer | Role | Format |
|-------|------|--------|
| `WIKI/pages/*.md` | **Source of truth** — durable, human-owned | OKF markdown |
| SME (Semantic Memory Engine) | Derived recall index | LanceDB vectors |
| RAG | Derived retrieval index | FTS5 + embeddings |

The vector stores are **rebuildable caches** over the markdown — `scribe wiki
distill` re-syncs changed pages into RAG. Delete the indexes and your knowledge
is intact; it lives in the files. This is the OKF promise: the knowledge is
portable across tools, and the index is a swappable implementation detail.

## Why it matters for a local-first tool

Because OKF is *just markdown in files*:

- Your distilled knowledge **never leaves your machine** and is **versioned with
  your code**.
- You can read and edit it in any editor, render it on GitHub, grep it.
- Another agent — Scribe or not — can consume the same files with no translation
  layer.

Local model, private knowledge, open format.
