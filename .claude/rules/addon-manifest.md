---
paths:
  - "*/config.yaml"
  - "*/Dockerfile"
  - "*/CHANGELOG.md"
  - ".github/workflows/*.yml"
---
# Add-on manifest rules (Home Assistant)
- Every release: bump `version` in `config.yaml` and add a matching top entry to `CHANGELOG.md` (newest first, `## x.y.z`).
- `options` defaults must satisfy `schema`; a new option needs a schema line, and removing one must not break existing user configs (keep it, mark unused).
- Ask for the minimum privileges: do not add `privileged`, `full_access`, `host_network`, `devices`, `apparmor: false` without a reason recorded in the add-on `HANDOFF.md`.
- `ingress: true` add-ons listen on `ingress_port` and must not require auth of their own; a `watchdog` URL must point to a real health endpoint.
- Persistent data lives in `/data` only. Never bake secrets into the image or the repo; secrets come from `options`.
- A CI workflow builds an add-on only if its `paths:` filter lists that add-on folder; a new image-based add-on needs its own workflow and an `image:` key in `config.yaml`.
- Dockerfile: pin base image tags and Python/npm dependency versions.
