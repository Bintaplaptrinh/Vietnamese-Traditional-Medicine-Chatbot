# Medical conversation profiles

Bloop adapts eight skills from [AIPOCH Medical Research Skills](https://github.com/aipoch/medical-research-skills)
at commit `686e09dfdb45d9fa1a08664f06bb93769b3c9d91`. Copyright and permission
notices are preserved in [LICENSE-AIPOCH](LICENSE-AIPOCH). The adapted profiles
are distributed under the same MIT license.

Each top-level `<skill-id>/SKILL.md` is a compact conversation adaptation. The
original skill Markdown and its supporting Markdown modules/assets are preserved
in `upstream/<skill-id>/` for attribution and review. [manifest.json](manifest.json)
records their pinned source URLs and SHA-256 hashes. Upstream scripts,
dependencies and evaluation reports are not part of the runtime package.

[`medical_skills.py`](../medical_skills.py) loads only the adapted profiles:

| Stage | Selection |
| --- | --- |
| Planner | Biomedical search strategy |
| Every answer draft | Claim verification, claim strength and reference integrity |
| Research question or study evidence | Study design |
| Conflict question or evidence conflict group | Contradictory findings |
| English answer | Medical English precision |
| Other answer languages, including Vietnamese | Plain language summary in the requested language |

Adaptations preserve evidence scope, terminology, uncertainty and attribution.
They replace manuscript/report templates with the host's JSON answer contract.
All writing guidance runs before independent JEV verification. Skills are
instructions, not evidence; they grant no tools, sources or additional calls.
Skill prompt characters count toward the existing input budget.

The application validates and caches this package on startup. A missing or invalid
profile fails startup instead of silently disabling guidance. No runtime network
download or reference clone is needed. Restart the backend after changing profiles.

`GET /api/health` exposes `skill_profile`. Each chat result and saved trace include
`skills`: version, fingerprint, upstream revision, planner IDs and draft IDs per
round. The fingerprint covers the manifest, adapted profiles, host adapter and
routing patterns. These fields identify instructions used; they do not establish
answer quality. Provider streaming and frontend text animation remain controlled
by the application code.
