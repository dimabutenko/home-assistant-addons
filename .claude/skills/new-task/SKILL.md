---
name: new-task
description: Create the next small task spec in an add-on's docs/tasks/ and register it in 00-index.md. Use before implementing any new piece of work in an add-on that follows the task flow (esp_rs_builder).
---
# new-task

Input: add-on folder + a one-line goal. Paths are relative to the add-on folder.

1. Read `CLAUDE.md`, `ARCHITECTURE.md`, `docs/tasks/00-index.md` (targeted; do not dump other files).
2. Pick the next number `NN` (two digits) and a short slug; create `docs/tasks/NN-<slug>.md` with exactly these sections:
   - **Goal** — one paragraph, the observable outcome.
   - **Scope** — concrete files/modules/behaviours in; say what is out.
   - **Constraints** — invariants from the add-on `CLAUDE.md` and `ARCHITECTURE.md`; dependency limits.
   - **Verification** — exact commands (see `docs/tasks/04-*.md` for style) and what "pass" means; name what cannot run here.
   - **Definition of Done** — checklist including index + `HANDOFF.md` updates.
3. The task must fit one session. If it does not, split it and write only the first part now.
4. Add a row to `docs/tasks/00-index.md` (`TODO`). If the task changes a decision, edit `ARCHITECTURE.md` in the same turn.
5. Write in English. Do not implement the task in the same step.
