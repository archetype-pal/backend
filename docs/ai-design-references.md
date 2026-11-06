# What the code's § references mean

The AI programme's code cites a design document by section (§7 to §11). That
document is in no repository. This page is **not** that document: it records
what the code says each section required, so a reader can follow a citation.
Nothing here comes from the original text, except the quotation under §8.5, as
the code quotes it. If the original turns up, it replaces this page.

| Section | What the code takes from it | Where |
|---|---|---|
| §7.2 | W1.1: a box detector trained on the existing glyph boxes, or a promptable segmentation model used zero-shot. W1.4: under 10% character error, measured against an off-the-shelf medieval-Latin model. | `apps/vision/services/detection.py`, `apps/vision/services/htr.py`, `apps/ml/evaluation.py` |
| §8.3 | A citation must be correct, not just clickable: it is resolved against the record before an answer may use it. A ledger entry is not enough for a machine draft: its lineage stays public and approval never clears it. | `apps/agents/tools.py`, `apps/manuscripts/services/regions.py`, `apps/diplomatic/pipelines/translation.py` |
| §8.5 | "No existing permission concept expresses a per-agent service identity with an explicit tool allow-list. Building one is a prerequisite of Phase 3." Least privilege is enforced by the credential, not the prompt, and an agent has a quota as well as a rate limit. | `apps/agents/models.py` |
| §8.6 | Reviewer time is the programme's real rate limit, and a stop rule reads the depth of the review queues. The code exposes the depth; nothing stops a pipeline on it. | `apps/diplomatic/pipelines/base.py`, `apps/diplomatic/services.py`, `apps/vision/services/detection.py` |
| §9.1 | The evaluation plan asks for a trivial baseline on raw pixels beside any vision model, to expose a model that recognises the photograph and not the script. | `apps/ml/evaluation.py`, `apps/ml/providers/pixels.py`, `apps/ml/providers/shape.py` |
| §10.4 | A replanning trigger: if an off-the-shelf baseline is already good enough, integrate it and do not train. | `apps/vision/services/htr.py` |
| §10.7 | A dataset release needs a licence statement before anything is published (an open item). | backend#202 |
| §11 | The programme publishes its limits, so an agent says what it cannot do. | `apps/agents/views.py` |
