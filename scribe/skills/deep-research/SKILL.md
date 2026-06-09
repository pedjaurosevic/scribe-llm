---
name: deep-research
description: Multi-step iterative research with source collection, claim verification, and structured output.
---

# Skill: deep-research

Multi-step research protocol for autonomous investigation of topics.

## When to Use

The user asks to research a topic deeply, compile evidence, verify claims, or produce a research dossier.

## Research Protocol

### 1. Plan

Identify 3-5 sub-questions the research must answer. State them clearly.

### 2. Search

Run 2-3 targeted web searches. Collect candidate URLs.

### 3. Fetch

Read the top 3-4 sources. For each, extract:
- Main claims
- Supporting evidence
- Date and credibility signals

### 4. Build Claim Register

Every important claim with source. Mark status:
- ✅ Verified (multiple independent sources)
- ⚠️ Partial (one source or weakly supported)
- ❓ Unverified (model knowledge only)
- ❌ Contradicted (sources disagree)

### 5. Gap Check

Identify what the research did not answer. Run one more targeted search if needed.

### 6. Synthesize

Write the final report with inline citations [1][2][3].

### 7. Save

Write to `~/.scribe/research/TOPIC-research.md`.

## Internal Language

Use the OBSERVATION/CLAIM/EVIDENCE/UNCERTAINTY format:

```
OBSERVATION: What was found in sources
CLAIM: What we assert based on evidence
EVIDENCE: Source citation or logical derivation
UNCERTAINTY: What remains unknown or unverified
```

## Quality Rules

- Never present unverified claims as confirmed facts
- Separate model prior knowledge from retrieved evidence
- If evidence is weak, say so plainly
- Prefer primary sources (official docs, papers) over blog summaries
- Save even incomplete research — mark status as "In progress"
