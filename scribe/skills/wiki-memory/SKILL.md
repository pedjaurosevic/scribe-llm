---
name: wiki-memory
description: Use the local wiki filesystem for durable project memory, architecture decisions, and long-term knowledge.
---

# Skill: wiki-memory

Local markdown memory filesystem for durable project knowledge.

## Overview

WIKI is not a vector database, not a crawler, and not an autonomous research loop.
It is a curated collection of important facts, decisions, research conclusions, and architecture notes.

## Layer Mapping

- Layer 1: Perception — tells when memory should be consulted
- Layer 3: State Manager — maintains durable memory outside active context
- Layer 5: Monitoring — requires traceability and careful handling of unsupported claims

## When to Use

- User asks for long-term direction, architecture, roadmap, or system evolution
- Task depends on prior decisions or project-specific knowledge
- Agent completes a meaningful step that should survive the session
- User asks to remember, consolidate, or preserve a conclusion

## Read Path

```
WIKI/index.md
  → relevant WIKI/pages/*.md
  → linked raw material or research citations
```

## Write Path

```
new fact / decision / conclusion
  → preserve raw note if needed in WIKI/raw/
  → update or create WIKI/pages/<topic>.md
  → append short entry to WIKI/log.md
```

## Research Path

```
web-research
  → citations in state/research_sources.jsonl
  → extracted/cache files in research_cache/
  → compiled memory page in WIKI/pages/
  → WIKI/log.md
```

## Inputs

- User instruction or accepted project decision
- Existing WIKI pages and raw notes
- Research citations from `state/research_sources.jsonl`
- Cached research material from `research_cache/`
- Relevant workspace files

## Outputs

- Updated `WIKI/index.md` when a new page is added
- Updated or new markdown pages under `WIKI/pages/`
- Optional preserved source notes under `WIKI/raw/`
- Short update entry in `WIKI/log.md`

## Safety / Guardrails

- Do not delete raw material unless user explicitly asks
- Do not rewrite large parts of WIKI without confirmation
- Do not store secrets, credentials, or sensitive personal data
- Do not promote speculation into durable memory; mark as open question
- Prefer concise memory pages over transcript dumps
- Link important external claims to citations
- If WIKI conflicts with verified runtime behavior, trust verified code

## Done Criteria

- Relevant memory was read before making a long-term decision
- New durable knowledge stored in correct layer
- Index points to important pages
- Log records meaningful changes
- Unsupported claims are marked
