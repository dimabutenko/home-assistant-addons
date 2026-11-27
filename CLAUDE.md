# CLAUDE.md — Rules for the whole repository

## Repository
- A Home Assistant add-on repository (`repository.yaml`): one folder per add-on, each with its own `config.yaml`, `Dockerfile`, `README.md`, `CHANGELOG.md`.
- Work only inside the add-on folder the task is about; do not touch other add-on folders.
- Anything specific to one add-on (code, docs, task specs, handoff) lives in that add-on's folder, including its own `CLAUDE.md` for technical rules of that add-on. Only what is shared by all add-ons belongs in the repo root.

## Development flow (the same for every add-on)
Paths below are relative to the add-on folder. An add-on that is developed this way has `ARCHITECTURE.md`, `HANDOFF.md` and `docs/tasks/`.

### 1. Context hygiene & small chunks
- Keep context lean: no huge multi-file dumps or verbose tool output; prefer targeted reads (offset/limit, grep) and short summaries.
- Work in small atomic tasks: `docs/tasks/NN-<slug>.md`, each with **Goal**, **Scope**, **Constraints**, **Verification**, **Definition of Done**.
- Do **at most 1–2 small tasks per turn/session**. Verify (build / tests / the relevant runner), then stop cleanly.

### 2. Docs-first & task tracking
- `ARCHITECTURE.md` is the master architectural reference. Change it when a decision changes, in the same turn.
- Keep `docs/tasks/00-index.md` current with statuses: `TODO`, `IN_PROGRESS`, `DONE`, `BLOCKED`.
- Create/refine the next task spec in `docs/tasks/` **before** implementing it.

### 3. Handoff protocol (`HANDOFF.md`)
Update `HANDOFF.md` at the end of every turn and whenever context gets long. It must contain:
1. Active task status.
2. Completed files/artifacts.
3. Key architectural/dependency decisions.
4. Open blockers/questions.
5. A **ready-to-paste prompt for the next session** pointing to the add-on folder, its `CLAUDE.md`, `ARCHITECTURE.md`, `HANDOFF.md` and the exact next `docs/tasks/XX-*.md`.

**End-of-task chat message:** when a task is finished (or the session should end), tell the user in chat — in a short message — that the next task starts in a **new chat**, and print the ready-to-paste prompt for it in a code block (same text as in `HANDOFF.md`). Do not just say "see HANDOFF.md".

### 4. Misc
- Don't add dependencies without recording the decision in `HANDOFF.md`.

## Git: commits, author, push
- **Commit often.** After each cohesive, verified unit of work (one atomic task, a docs/config fix, a self-contained add-on change) make a small commit; do not bundle unrelated changes. Stage explicit paths of the add-on being worked on, never `git add -A`; never commit secrets.
- **The user is the only author.** Commits use the configured `git config user.name` / `user.email` (currently `Dzmitry Butenka <dima@butenka.com>`); never change the identity, and never add `Co-Authored-By` or other AI/assistant trailers or attribution lines, even if a tool or reminder suggests them (this rule overrides them).
- **Never run `git push` without explicit approval.** When commits are ready, stop and ask, stating: remote and branch, the commits to be pushed, and whether a force-push is involved. Push only after the user says yes; use `--force-with-lease`, never a bare force, and only when approved.
- Commit messages are in English; write the message with a plain `-m` string or the Write tool, not a heredoc containing guard-trigger text.
- If a toolchain is missing, say so plainly in the handoff — never claim verification that did not run.

## Claude tooling (`.claude/`)
- Skills: `new-task` (spec + index row), `handoff` (HANDOFF.md + next-session prompt), `addon-check` (manifest/version/CI consistency; per-add-on facts in its `reference.md`).
- Subagents (model → fallback if the alias is unavailable): `repo-scout` haiku → sonnet (status sweeps); `task-writer` sonnet → opus (implements one specified task); `addon-reviewer` opus → sonnet (privileges/security/data-safety review). `haiku` is never used for code, security or add-on reviews; the review fallback is `opus → sonnet` only.
- **Default model of this repo: `sonnet`** (set as `model` in `.claude/settings.json`); fallback `opus`, never `haiku` for code work. Use `opus` for architecture, privilege/security and migration decisions.
- The Bash/PowerShell `guard-bash` hook comes from the user-level `hobby-kit` plugin, not from this repo, and scans the whole command text. A command whose text contains a force-push, or a secrets-file name such as `.env` next to `cat`/`grep`/`head`, is blocked even inside a heredoc. Write such text (docs, rules, settings) with the Write/Edit tools instead of shell heredocs. It cannot be tuned from this repo.
- An add-on that does not yet follow the task flow stays lightweight (its CHANGELOG and tests are the record). Adopt the flow (`ARCHITECTURE.md`, `HANDOFF.md`, `docs/tasks/`) for an add-on only when a multi-step task on it needs it, and create those files inside that add-on's folder at that moment, not in advance.
- Toolchain quirks and verification state of an add-on (e.g. which shell has its compiler, what was last run) are recorded in that add-on's own `HANDOFF.md`/`CLAUDE.md`, never here.
- Continue in the same chat vs. a new one: stay when context is light and the next task reuses what is loaded; start a new chat when context is heavy with diffs/logs or the next task is a different subsystem (re-reading `ARCHITECTURE.md` + `HANDOFF.md` + the task spec is cheaper). State this judgment in `HANDOFF.md`. Give a next-session prompt only if a next planned step exists; after the final planned step say that none remains.
- Path-scoped rules in `.claude/rules/` load only when matching files are touched (add-on manifests, per-add-on technical notes, task docs).
- `.claude/settings.json` allows read-only git and the add-on test runners, allows `git commit`, asks before `git push`, denies secret files and destructive git. Personal overrides go to `.claude/settings.local.json` (git-ignored).
- Home Assistant add-on rules (version ↔ CHANGELOG, minimal privileges, `/data` only, no secrets in the repo) live in `.claude/rules/addon-manifest.md`.
