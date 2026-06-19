---
name: teach
description: Stateful tutor — keeps your mission and lessons in local files so progress survives across sessions without bloating the context.
user-invocable: true
disable-model-invocation: true
---

# Skill: teach

Learn a topic with a tutor that remembers *in files*, not in the context
window. Instead of carrying the whole history in tokens, the agent writes and
updates small Markdown files in the workspace — a mission file (what you want
to learn and where you are) and per-lesson files — and reads them back when it
needs context. A 12B model stays sharp because the state lives on disk, not in
an ever-growing prompt. Manually invoked; the model never starts it on its own.

## When to use

You want to learn a concept or skill over several sessions and have the tutor
pick up exactly where you left off.

## State files (under the workspace `learning/` directory)

- `learning/<topic>/mission.md` — the goal, your current level, and a checklist
  of milestones with `[ ]` / `[x]` status. Updated every session.
- `learning/<topic>/lesson-NN.md` — each lesson: explanation, a worked example,
  and 2–3 practice questions with answers.

## Procedure

1. **Resume or start.** If `mission.md` exists, read it first and summarize
   where the learner is. If not, ask what they want to learn and their current
   level, then write `mission.md` with a milestone checklist.
2. **Teach one milestone.** Explain the next milestone simply, give one worked
   example, then ask 2–3 questions. Save it as the next `lesson-NN.md`.
3. **Check understanding.** Grade the answers. If shaky, re-teach differently;
   do not advance until the milestone is solid.
4. **Update state.** Tick the milestone in `mission.md` and note any
   misconceptions to revisit. Keep these files short — they are memory, not prose.

## Rules

- Always read `mission.md` before teaching, so you never repeat or skip.
- Keep the state files small and current; they replace conversation history.
- Teach, then test. Never advance past a milestone the learner hasn't shown.
