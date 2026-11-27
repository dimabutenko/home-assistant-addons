---
name: handoff
description: End-of-task protocol - update the add-on's HANDOFF.md and 00-index.md, then print the next-session prompt in chat. Use at the end of every turn that changed an add-on, or when context gets long.
---
# handoff

Paths are relative to the add-on folder.

1. Set statuses in `docs/tasks/00-index.md` (`TODO`/`IN_PROGRESS`/`DONE`/`BLOCKED`).
2. Rewrite `HANDOFF.md` with these sections: **Status** (active task), **Completed artifacts**, **Decisions** (architecture, new dependencies with versions), **Blockers / open questions**, **Environment notes**, **Prompt for next session**.
3. State plainly what was verified and what could not run (missing toolchain, no hardware, no Home Assistant). Never claim a check that did not run.
4. The prompt names the add-on folder, its `CLAUDE.md`, `ARCHITECTURE.md`, `HANDOFF.md` and the exact next `docs/tasks/NN-*.md`, plus what to update when done.
5. In chat (Russian), tell the user in a short message that the next task starts in a **new chat** and print the same prompt in a code block. Do not just point to `HANDOFF.md`.
6. Commit the finished, verified work in small commits as the repo `CLAUDE.md` "Git" section says (user is the only author, no AI trailers). Never push without explicit approval.
