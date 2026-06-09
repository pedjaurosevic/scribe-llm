---
name: writer
description: Versatile writing assistant for essays, fiction, articles, reports, scripts, and books.
---

# Skill: writer

Versatile prose drafting with attention to style, tone, and eliminating AI-isms.

## When to Use

The user wants to write something: a new piece from scratch, a continuation of existing work, or a revision.

## Workflow

### Starting from Scratch

1. Identify format: essay, article, fiction, script, email, report, speech
2. Gather parameters: topic, audience, tone, approximate length, constraints
3. Draft directly without preambles
4. Save if substantial (>300 words) to `~/.scribe/drafts/`

### Continuing Existing Work

1. Read the full existing piece
2. Match voice and style: tense, register, sentence rhythm
3. Continue from the stopping point
4. Note research gaps with `[VERIFY: X]`

### Revising

1. Read the full draft first
2. Identify the problem: structure, voice, clarity, length, argument
3. Rewrite only what was asked to fix
4. Show revised version as replacement, not diff

## Format Selection

| Request | Format |
|---------|--------|
| News article, explainer | Inverted pyramid — most important first |
| Essay, opinion | Argument first, evidence second, conclusion |
| Fiction | Scene-by-scene; show don't tell |
| Email, letter | Direct opener, one ask, clear close |
| Report | Summary → findings → recommendations |
| Script / dialogue | Slug lines, action lines, character cues |
| Social post | One clear idea, no padding |

## Quality Rules

- Write in the voice the user specifies, or match existing voice
- Do not add disclaimers, preambles, or meta-commentary inside prose
- Mark uncertain facts `[VERIFY: X]` — do not invent
- Prefer concrete over abstract
- Default output language: match user's language

## Voice Guidelines (for avoiding AI-isms)

- Vary sentence length — avoid uniform rhythm
- Use specific details over vague gestures
- Avoid formulaic transitions ("Furthermore...", "In conclusion...")
- Prefer active voice over passive
- Cut unnecessary qualifiers ("very", "really", "quite")
