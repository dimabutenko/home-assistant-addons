---
name: addon-check
description: Consistency check of a Home Assistant add-on folder - config.yaml keys, version vs CHANGELOG, Dockerfile, CI workflow path filter, and the add-on's own tests. Use before a release or a commit.
---
# addon-check

Given an add-on folder, check (read-only unless told to fix). Details and per-add-on facts: [reference.md](reference.md).

1. `config.yaml`: required keys (`name`, `version`, `slug` = folder name with `_`, `description`, `arch`), `options` vs `schema` consistent.
2. `CHANGELOG.md` top entry equals `config.yaml` `version`.
3. `Dockerfile` exists and `COPY` paths exist; base image and dependencies pinned.
4. Privileges requested (`privileged`, `devices`, `apparmor: false`, `map`) are justified.
5. A workflow in `.github/workflows/` covers the folder, if the add-on has an `image:` key.
6. Run the add-on's checks from `reference.md`; report what passed, failed, and what could not run.

Output: a short table of check / result / evidence. Do not fix silently.
