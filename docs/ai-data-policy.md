# AI data policy (W0.4) — DRAFT

> **Draft, for the project to decide. Not agreed and not published.**
> The policy is the project's decision, not the code's. This draft is written
> from what the code on the `ai-programme` branch enforces as of 6 November
> 2026, so that the decision starts from what is true. Each rule below names
> where it is enforced; the gaps between what is enforced and what a policy
> needs are listed in [What the code does not decide](#what-the-code-does-not-decide),
> and the questions only the project can answer in [Decisions](#decisions).
>
> The programme committed to writing and publishing this policy *before* any
> partner material is processed (`docs/roadmaps/ai-programme-scientists.md`).
> Until it is agreed, the hosted switch stays off on every deployment.

## What it covers

What corpus material, and what users give us, may be sent to a model, and
which models; what is kept about each call; and what may be published from
what the models were trained or run on.

The corpus material in question:

- **The photographs.** Each holding repository's photography of its charters.
  None is cleared for redistribution today: every repository's
  `derivative_release` is `unknown` until someone asks the archive and records
  its answer in writing (`apps/manuscripts/models.py`, `Repository.DerivativeRelease`;
  `manage.py rights_report` lists them).
- **The texts.** Transcriptions and edition texts (`ImageText`, TEI).
- **The annotations.** Boxes, allographs and hands: the project's own work.
- **What users give us.** A question typed to the agent, a picture a student
  uploads to the tutor.

## Two kinds of model

Every model is registered once, in `apps/ml/providers/registry.py`, and each
registration says whether a call leaves our infrastructure (`hosted`). The
inference service reads that flag; it is not a comment.

**Self-hosted** (`hosted=False`): the material stays on our server.

| Provider | What it is | Licence | Used for |
| --- | --- | --- | --- |
| `letters` | Two ResNet-18s fine-tuned on this corpus's expert boxes, in the HTR service | torchvision BSD-3, ImageNet weights | Proposing a page's letters (W1.1) |
| `kraken` | Kraken with CATMuS Medieval 1.5.0, in the HTR service | Apache-2.0; CC-BY 4.0 | Reading lines (W1.4 baseline), and the lines the letter models start from |
| `trocr` | The vision encoder of TrOCR Manicule 2026 Latin Medieval, in the embedder service | MIT | Glyph vectors (W1.2, W1.3) |
| `pixels`, `ink`, `hog`, `hog-page` | Not models: image descriptors computed in-process | — | Baselines, page search (W3.4) |
| `null` | Echo, for tests | — | — |

**Hosted** (`hosted=True`): the material is sent to a third party.

| Provider | Recipient | Used for |
| --- | --- | --- |
| `claude` | Anthropic's API, directly | Drafting a page's transcription (W1.4), the tutor (W4.4) |
| `openrouter` | OpenRouter, which forwards to an upstream it chooses per request | The agent (W3.1), diplomatic pipelines (phase 2), the HTR baseline and the hosted glyph-detection comparison (commands) |

## What the code enforces

### Nothing runs until someone switches it on

Both switches default to off (`config/settings.py`):

- `ML_INFERENCE_ENABLED` — every model, self-hosted or hosted.
- `ML_HOSTED_PROVIDERS_ENABLED` — the hosted ones, in addition.

Both are checked when a call is submitted and again in the worker when it
runs (`apps/ml/services/inference.py`, `_check_policy`), so switching either
off also stops work already queued. A refused call is still a ledger row.

### Every call is recorded, but not what it was sent

Every model call, self-hosted or hosted, goes through one service and leaves
one `MLJob` row (`apps/ml/models.py`): the task, the provider, the model and
its version, who asked, the tokens, the cost, the time taken and the outcome.

The row holds **digests, not the material**: `input_ref` is a SHA-256 of the
inputs and `prompt_hash` of the prompt. Neither the inputs nor the output are
stored in the ledger, because that would be a second copy of the corpus
material this policy governs (`apps/ml/services/inference.py`). What a model
produced is kept only where it is filed for review (below).

### Spend is capped

Two caps over a rolling 24 hours, in millionths of a currency unit:
`ML_DAILY_COST_CAP_MICROS` for everything, and
`ML_DAILY_COST_CAP_MICROS_PER_ACTOR` per user (`apps/ml/services/budget.py`).
The total defaults to $10, and a hosted provider is refused unless it is above
0. Setting the per-user cap to 0 disables it.
They are computed from the ledger and checked before each call and again in
the worker. The agent and the tutor have their own throttles on top
(`DRF_THROTTLE_AGENT_RATE`, `LEARN_DAILY_SESSIONS`, `DRF_THROTTLE_LEARN_RATE`).

### OpenRouter is restricted to upstreams that do not train on prompts

OpenRouter chooses the upstream that receives each request. It is asked to
route only to upstreams that, by OpenRouter's account, do not log prompts for
training (`data_collection: "deny"`, unless `ML_OPENROUTER_ALLOW_DATA_COLLECTION`
is on). OpenRouter calls that account "our best knowledge", not a guarantee
(`apps/ml/providers/openrouter.py`). `ML_OPENROUTER_ALLOWED_PROVIDERS` names
the upstreams outright, if that is not enough.

### Glyph crops go only to a self-hosted model

Glyph vectors are computed only by a self-hosted encoder. A hosted provider
is refused before a crop is fetched (`apps/vision/services/embedding.py`).

### No pixels are published without the archive's written consent

- The glyph dataset release holds geometry, labels and IIIF region references,
  and no image data (`apps/datasets/export.py`). A crop release is gated on
  `may_redistribute_crops`, which refuses anything not cleared in writing
  (`apps/manuscripts/services/rights.py`).
- A IIIF manifest states a rights statement only when every image it covers
  shares that statement, so one permissively licensed image cannot lend its
  terms to an archive's (`apps/annotation_standards/manifest.py`).

### What a model produces is reviewed before it enters the record (C1)

No model writes to the canonical record. What it produces is filed for review
and enters the record only when a named person accepts it:

- Letters proposed for a page become `GraphProposal`s in the review queue
  (`apps/annotations/services/proposals.py`). A reviewer accepts, corrects or
  rejects each one.
- A drafted transcription is filed as a Draft `ImageText`, marked as
  machine-drafted in its TEI, and goes through the usual Draft → Review → Live
  workflow (`apps/vision/services/page_drafts.py`).
- What a diplomatic pipeline extracts is a `Proposal` until someone accepts it
  (`apps/diplomatic/models.py`).

From the backoffice, drafting a transcription and proposing letters each run
only when a user asks for one page. Only an operator at the command line can
run either over many pages (`htr_baseline`, `propose_letters`, each with a
`--limit`).

### What users give us

- **The agent (W3.1).** A question is kept in full with what the agent did
  (`AgentRun`): it is the user's own words, not corpus material, and the only
  record of what the agent was asked. Raw client IP addresses are not stored
  (`apps/agents/models.py`).
- **The tutor (W4.4).** By default only a signed-in user may upload a picture
  (`LEARN_UPLOADS`). Uploads are stored outside the media directory, so they
  are reachable only through their session, and are deleted with the session
  after `LEARN_RETENTION_DAYS` (30) by `prune_tutor_sessions`, which the
  deployment runs daily. An upload is sent to Anthropic with the rest of the
  lesson.

### What may not leave this server

`export_letter_pages` writes the photographs the letter models train on. Its
documentation says the directory is for training on this server, never for
publishing. **This is a convention, not a check.** The same holds for the
trained weights (see below).

## What each feature sends

| Feature | Trigger | Provider | Sent off our server |
| --- | --- | --- | --- |
| Proposing a page's letters (W1.1) | A manager, one page at a time; or a command | `letters` | Nothing |
| Glyph vectors (W1.2, W1.3) | Command | `trocr` | Nothing |
| Page search (W3.4) | A manager, one page at a time | `hog-page` | Nothing |
| Drafting a page's transcription (W1.4) | A manager, one page at a time | `claude` | **The page's photograph** (up to 2,576 px) |
| HTR baseline and evaluation (W1.4, `htr_baseline`) | Command | `openrouter` by default; `kraken` or `claude` if named | **Page photographs**, unless run with `kraken` |
| Hosted glyph detection (W1.1, kept for comparison) | Command | `openrouter` | **Page photographs** |
| The tutor (W4.4) | Anyone, throttled; an upload needs a sign-in by default | `claude` | **Corpus photographs, and the student's own picture** |
| The agent (W3.1) | Anyone, throttled | `openrouter` | The question, and the corpus text and records its tools look up |
| Diplomatic pipelines (phase 2) | Command | `openrouter` by default | **Charter texts** |

## What the code does not decide

1. **The hosted switch is one switch for everything.** Turning
   `ML_HOSTED_PROVIDERS_ENABLED` on lets every hosted feature in the table
   above send photographs from every repository. No hosted call checks the
   repository's rights first. The rights fields we hold answer a different
   question: whether crops may be *redistributed*, not whether a photograph
   may be sent to a model provider to be *processed*. Nothing records an
   archive's answer to the second question.
2. **Who receives the material through OpenRouter is not fixed** unless
   `ML_OPENROUTER_ALLOWED_PROVIDERS` names them. The non-logging restriction
   relies on OpenRouter's account of its upstreams.
3. **What the hosted providers keep, and for how long, is set by their terms,
   not by us.** This draft does not state them. They should be read and
   recorded, with a date, for Anthropic's API and for each upstream OpenRouter
   may use, before the policy is agreed.
4. **The trained weights and the training pages.** The letter models are
   fine-tuned on uncleared photographs. Nothing stops anyone publishing the
   weights or the exported pages; only a convention does.
5. **Texts.** Transcriptions and edition texts are sent to hosted models by
   the agent and the diplomatic pipelines. Nothing distinguishes texts whose
   rights are the project's own from texts taken from a published edition.

## Decisions

Proposals, for the project to accept, change or refuse.

1. **Which repositories' photographs may be sent to a hosted model, and on
   whose answer?** Proposal: record each archive's answer per repository, as
   `derivative_release` records redistribution, defaulting to "not asked"
   (refuse), and have each hosted call that sends a photograph check it.
   Until then, the hosted switch stays off wherever partner photographs are
   held.
2. **Which recipients are acceptable?** For example: Anthropic's API directly,
   and OpenRouter only with named upstreams.
3. **Are texts treated like photographs?** Proposal: the project's own
   transcriptions and annotations may be sent; edition texts follow the
   edition's terms.
4. **Students' pictures.** Signed-in users only, or anyone? Is 30 days the
   right retention?
5. **The trained weights.** May models fine-tuned on partner photographs be
   published, shared with partners or kept on our server only? Proposal: kept
   on our server until the archives whose photographs trained them have been
   asked.
6. **Where it is published.** Proposal: on the public site, with the date it
   was agreed, before any partner material is sent to a hosted model.
