# HANDOFF — repo-level tooling (`.claude/`, root `CLAUDE.md`)

Add-on work has its own `HANDOFF.md` inside the add-on folder. This file covers shared tooling only.

## Status
- Tooling bootstrap and its verification pass: **DONE**. No further planned step for the tooling.

## Completed artifacts
- Root `CLAUDE.md` (flow + "Claude tooling" section), `.gitignore`.
- `.claude/settings.json` (default `model: sonnet`, permissions), `.claude/rules/` (4), `.claude/skills/` (`new-task`, `handoff`, `addon-check`), `.claude/agents/` (3).

## Decisions
- Default model `sonnet`, fallback `opus`; never `haiku` for code, security or add-on reviews.
- Subagents: `repo-scout` haiku → sonnet; `task-writer` sonnet → opus; `addon-reviewer` opus → sonnet.
- `guard-bash` is the user-level `hobby-kit` plugin hook, not part of this repo; it blocks command text containing a force-push or a secrets-file name next to a reader command, even in heredocs. Mitigation: write docs/settings with Write/Edit, not shell heredocs.
- Add-ons adopt the task flow on demand, inside their own folder, when a multi-step task needs it; nothing is pre-generated for untouched add-ons.

## Verification state
- Frontmatter/JSON of the new files was checked by a script in this pass; the skills/agents were not exercised.

## Token/context judgment
- Tooling work is finished; no add-on work is carried here. Add-on tasks start in their own chat from that add-on's `HANDOFF.md`.

## Next session
No next step for this tooling.
