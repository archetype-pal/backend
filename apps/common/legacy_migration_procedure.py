from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from apps.common.legacy_migration_audit import AuditReport, report_to_dict

PROCEDURE_VERSION = "2026-05-29"


@dataclass(frozen=True)
class SafetyGate:
    key: str
    title: str
    rule: str
    evidence: str


@dataclass(frozen=True)
class MigrationPhase:
    key: str
    title: str
    objective: str
    source_tables: tuple[str, ...]
    target_tables: tuple[str, ...]
    importer_contract: tuple[str, ...]
    validation: tuple[str, ...]
    rollback: str


SAFETY_GATES: tuple[SafetyGate, ...] = (
    SafetyGate(
        key="compose_only",
        title="Run through Docker Compose",
        rule="Run backend migration commands in the Compose API container, not host Python.",
        evidence="Command log shows docker compose run/exec for every DB operation.",
    ),
    SafetyGate(
        key="backups_required",
        title="Backups before writes",
        rule="Create verified custom-format dumps of legacy and target databases before any write importer runs.",
        evidence="Manifest records dump filenames, checksums, sizes, and storage location.",
    ),
    SafetyGate(
        key="separate_databases",
        title="Refuse same source and target",
        rule="The legacy URL and target URL must resolve to different database names.",
        evidence="Preflight/audit exits before import when the names match.",
    ),
    SafetyGate(
        key="audit_gate",
        title="Read-only audit gate",
        rule="Run audit_legacy_migration first. Treat fail as a blocker and require sign-off for warnings.",
        evidence="Manifest stores audit output path, status, and accepted warnings.",
    ),
    SafetyGate(
        key="empty_target_default",
        title="Empty target by default",
        rule="Run the write importer only against a freshly migrated target DB unless explicitly approved.",
        evidence="Preflight row-count report is attached to the manifest.",
    ),
    SafetyGate(
        key="author_policy",
        title="Publication author policy",
        rule="Do not map publication authors by legacy numeric id. Use username/email mapping or a fallback author.",
        evidence="Manifest records the chosen author policy and sample resolved posts.",
    ),
    SafetyGate(
        key="phase_transactions",
        title="Transaction per phase",
        rule="Each import phase must be atomic and independently auditable.",
        evidence="Manifest records phase start/end time, status, row counts, and rollback reference.",
    ),
    SafetyGate(
        key="sequence_reset",
        title="Reset sequences after explicit ids",
        rule="Run sequence synchronization after id-preserving imports and before application writes resume.",
        evidence="Manifest records just sync-sequences output or equivalent SQL result.",
    ),
    SafetyGate(
        key="target_only_policy",
        title="Target-only data is not legacy data",
        rule=(
            "Create current-only workflow/product rows only from current-system sources, "
            "never by guessing legacy source data."
        ),
        evidence="Manifest records skipped target-only tables or the approved current-system source for each.",
    ),
)


MIGRATION_PHASES: tuple[MigrationPhase, ...] = (
    MigrationPhase(
        key="00_preflight",
        title="Preflight",
        objective="Confirm environment, database URLs, schema state, table availability, and target readiness.",
        source_tables=("legacy source public schema",),
        target_tables=("Django migration table", "current public schema"),
        importer_contract=(
            "Verify legacy and target URLs are present and point to different databases.",
            "Run the read-only audit before any write step.",
            "Collect target migration state and current domain row counts.",
            "Stop if the target is non-empty unless an explicit audit/update mode is approved.",
        ),
        validation=(
            "audit_legacy_migration exits without fail status.",
            "showmigrations reports all expected target migrations applied.",
            "Manifest contains operator, environment, source dump, target dump, and approval fields.",
        ),
        rollback="No rollback needed; this phase must be read-only.",
    ),
    MigrationPhase(
        key="01_backups",
        title="Backups And Restore Point",
        objective="Create restorable source and target snapshots before trial or production imports.",
        source_tables=("legacy source database",),
        target_tables=("target database",),
        importer_contract=(
            "Create pg_dump custom-format dumps for legacy and target databases.",
            "Record sha256 checksums and byte sizes in the manifest.",
            "Store dumps outside the live Postgres Docker volume.",
        ),
        validation=(
            "pg_restore --list succeeds for every dump.",
            "Checksums in the manifest match the stored files.",
        ),
        rollback="Restore the target dump with pg_restore after dropping/recreating the target DB.",
    ),
    MigrationPhase(
        key="02_users_authors",
        title="Users And Publication Authors",
        objective="Define the identity policy required before publication rows can be imported safely.",
        source_tables=("auth_user", "blog_blogpost"),
        target_tables=("auth_user", "publications_publication"),
        importer_contract=(
            "Map legacy users by username/email, or select one explicit fallback author.",
            "Do not rely on numeric legacy auth_user ids in a fresh target.",
            "Record original legacy username/email where the fallback author is used.",
        ),
        validation=(
            "Publication author audit warning is either eliminated or explicitly accepted.",
            "Sample migrated publication authors resolve to expected target users.",
        ),
        rollback="Delete imported publications for the phase or restore the target backup.",
    ),
    MigrationPhase(
        key="03_core_vocabularies",
        title="Core Vocabularies",
        objective="Import stable shared vocabularies before dependent manuscript rows.",
        source_tables=("digipal_date", "digipal_format", "digipal_source", "digipal_repository"),
        target_tables=(
            "common_date",
            "manuscripts_itemformat",
            "manuscripts_bibliographicsource",
            "manuscripts_repository",
        ),
        importer_contract=(
            "Preserve ids where the audit says ids are preserved.",
            "Keep target-only date seed rows documented and do not overwrite them.",
            "Apply repository label/type/place transformations explicitly.",
        ),
        validation=(
            "Audit mappings for dates, item formats, sources, and repositories match accepted warnings.",
            "Foreign key lookups used by manuscript phases resolve.",
        ),
        rollback="Delete rows imported by this phase after dependent phases are rolled back, or restore backup.",
    ),
    MigrationPhase(
        key="04_symbols",
        title="Symbol Structure",
        objective="Import characters, allographs, components, features, and positions before graph annotations.",
        source_tables=(
            "digipal_character",
            "digipal_allograph",
            "digipal_component",
            "digipal_feature",
            "digipal_aspect",
        ),
        target_tables=(
            "symbols_structure_character",
            "symbols_structure_allograph",
            "symbols_structure_component",
            "symbols_structure_feature",
            "symbols_structure_position",
        ),
        importer_contract=(
            "Preserve ids for direct vocabularies.",
            "Keep documented placeholder ids such as allograph -1 explicit.",
            "Skip known stale/duplicate rows only when listed in the accepted audit warnings.",
        ),
        validation=(
            "Unique allograph/component/position constraints pass.",
            "Audit mappings for symbol tables are ok or match accepted warnings.",
        ),
        rollback="Delete symbol rows only before annotations are imported, or restore backup.",
    ),
    MigrationPhase(
        key="05_manuscripts",
        title="Manuscripts And Images",
        objective="Import manuscript hierarchy and IIIF-backed item images.",
        source_tables=(
            "digipal_currentitem",
            "digipal_historicalitem",
            "digipal_description",
            "digipal_cataloguenumber",
            "digipal_itempart",
            "digipal_itempartitem",
            "digipal_image",
        ),
        target_tables=(
            "manuscripts_currentitem",
            "manuscripts_historicalitem",
            "manuscripts_historicalitemdescription",
            "manuscripts_cataloguenumber",
            "manuscripts_itempart",
            "manuscripts_itemimage",
        ),
        importer_contract=(
            "Preserve ids for current items, historical items, descriptions, catalogue numbers, "
            "item parts, and images.",
            "Create the documented -1 item-part placeholder only if needed.",
            "Validate shortened shelfmark/current locus fields before insert.",
        ),
        validation=(
            "All manuscript foreign keys are valid.",
            "Item image counts match the audit.",
            "Sample IIIF image paths resolve in the application.",
        ),
        rollback="Delete imported manuscript rows in reverse dependency order or restore target backup.",
    ),
    MigrationPhase(
        key="06_scribes_hands",
        title="Scribes And Hands",
        objective="Import scribes, hands, and image-hand links after item parts and images exist.",
        source_tables=("digipal_scribe", "digipal_script", "digipal_hand", "digipal_hand_images"),
        target_tables=("scribes_scribe", "scribes_script", "scribes_hand", "scribes_hand_item_part_images"),
        importer_contract=(
            "Preserve ids for scribes, scripts, hands, and hand-image links.",
            "Create documented placeholder scribe -1 only if needed.",
            "Map legacy display order into num/priority/is_default according to product policy.",
        ),
        validation=(
            "Hand ordering works for sampled item parts.",
            "Audit mappings for scribes, hands, and hand-image links match accepted warnings.",
        ),
        rollback="Delete hand-image links, hands, and scribes for the phase or restore backup.",
    ),
    MigrationPhase(
        key="07_image_text",
        title="Image Text",
        objective="Import non-empty transcription/translation XML as target image text rows.",
        source_tables=("digipal_text_textcontentxml",),
        target_tables=("manuscripts_imagetext",),
        importer_contract=(
            "Import only rows with non-empty content.",
            "Do not preserve legacy XML ids unless a later importer design explicitly requires it.",
            "Leave review_assignee_id, status transitions, and content_dpt_legacy to current workflows.",
        ),
        validation=(
            "Legacy text exclusions check reports matching non-empty XML and ImageText counts.",
            "Unique one-text-per-image/type constraint passes.",
        ),
        rollback="Delete image text rows imported by the phase or restore target backup.",
    ),
    MigrationPhase(
        key="08_annotations",
        title="Annotations And Graph Details",
        objective="Import image/text/editorial annotations and graph through tables after symbols, hands, and images.",
        source_tables=(
            "digipal_annotation",
            "digipal_graph",
            "digipal_idiograph",
            "digipal_graphcomponent",
            "digipal_graphcomponent_features",
            "digipal_graph_aspects",
        ),
        target_tables=(
            "annotations_graph",
            "annotations_graphcomponent",
            "annotations_graphcomponent_features",
            "annotations_graph_positions",
        ),
        importer_contract=(
            "Preserve legacy annotation ids for Graph rows.",
            "Filter graph components/features/positions consistently with omitted graph material.",
            "Require allograph and hand for image graphs; text/editorial links may follow accepted legacy shape.",
        ),
        validation=(
            "Annotation shape check has no fail status.",
            "Graph component and position counts match accepted audit warnings.",
            "Sample image annotations render in viewer/API responses.",
        ),
        rollback="Delete graph through rows first, then graph rows for the phase, or restore target backup.",
    ),
    MigrationPhase(
        key="09_publications",
        title="Publications And Carousel",
        objective="Import public CMS records represented in the current application.",
        source_tables=("blog_blogpost", "blog_blogpost_categories", "digipal_carouselitem"),
        target_tables=(
            "publications_publication",
            "publications_publication_keywords",
            "publications_carouselitem",
        ),
        importer_contract=(
            "Use the approved author policy from phase 02.",
            "Preserve publication and carousel ids where the audit says ids are preserved.",
            "Re-key keyword/category joins through current tagulous tables.",
        ),
        validation=(
            "Publication counts match the audit.",
            "Sample slugs, statuses, publication dates, and author displays are correct.",
        ),
        rollback="Delete publication keyword links, publications, and carousel rows for the phase or restore backup.",
    ),
    MigrationPhase(
        key="10_target_only",
        title="Target-Only Current Data",
        objective="Handle current-only tables without inventing unsupported legacy source mappings.",
        source_tables=("current-system sources only",),
        target_tables=(
            "common_editevent",
            "manuscripts_historicalitemdateassessment",
            "manuscripts_statustransition",
            "worksets_workset",
        ),
        importer_contract=(
            "Do not derive edit events, status transitions, or worksets from legacy source data without a "
            "product decision.",
            "Create historical item date assessments only from approved current target metadata.",
            "Record skipped target-only tables in the manifest.",
        ),
        validation=(
            "Target-only warnings in the audit are accepted and documented.",
            "No unsupported legacy source table is used for target-only workflow data.",
        ),
        rollback="Delete current-only rows created during the phase or restore target backup.",
    ),
    MigrationPhase(
        key="11_final_validation",
        title="Final Validation",
        objective="Prove the imported target is internally consistent and application-ready.",
        source_tables=("all mapped legacy tables",),
        target_tables=("all target domain tables",),
        importer_contract=(
            "Run full audit_legacy_migration.",
            "Run sequence synchronization.",
            "Run focused tests and smoke checks.",
            "Rebuild Meilisearch indexes after target validation.",
        ),
        validation=(
            "Audit has no fail status and all warnings are listed in the manifest.",
            "Foreign key checks and target constraints pass.",
            "Search indexes rebuild successfully.",
        ),
        rollback="Restore target backup if validation fails after import phases have committed.",
    ),
    MigrationPhase(
        key="12_cutover",
        title="Deployment Cutover",
        objective="Promote the validated target database as a deliberate deployment operation.",
        source_tables=("validated target database",),
        target_tables=("production target database",),
        importer_contract=(
            "Run as a manual deployment job with explicit approval.",
            "Attach final manifest, final audit, and rollback instructions to the deployment record.",
            "Keep the legacy source database read-only until post-cutover acceptance is complete.",
        ),
        validation=(
            "Application smoke checks pass.",
            "API docs and key public endpoints respond.",
            "Business owner signs off sampled migrated records.",
        ),
        rollback="Restore the pre-cutover target dump and return traffic to the previous deployment.",
    ),
)


COMMANDS: tuple[tuple[str, str], ...] = (
    (
        "Generate the operator guide",
        "docker compose run --rm api python manage.py legacy_migration_procedure "
        "--output docs/legacy-migration-operator-guide.md "
        "--manifest-template docs/legacy-migration-manifest-template.json",
    ),
    (
        "Generate the guide with a live read-only audit summary",
        "docker compose run --rm api python manage.py legacy_migration_procedure "
        "--with-live-audit --output docs/legacy-migration-operator-guide.md "
        "--manifest-template docs/legacy-migration-manifest-template.json",
    ),
    (
        "Refresh the checked-in audit snapshot",
        "docker compose run --rm api python manage.py audit_legacy_migration "
        "--format markdown --output docs/legacy-migration-audit.md",
    ),
    (
        "Plan the legacy import without writing data",
        "docker compose run --rm api python manage.py migrate_legacy_data "
        "--manifest docs/legacy-migration-import-dry-run.json",
    ),
    (
        "Run the legacy import against a fresh target database",
        "docker compose run --rm api python manage.py migrate_legacy_data --execute "
        "--publication-author-username <target-author-username> "
        "--allow-warnings --manifest docs/legacy-migration-import-run.json",
    ),
    (
        "Run strict audit in CI or pre-cutover",
        "docker compose run --rm api python manage.py audit_legacy_migration --fail-on-warning",
    ),
    ("Synchronize target sequences after explicit ids", "just sync-sequences"),
    ("Rebuild search after final validation", "just sync-all-search-indexes"),
)


def build_manifest_template(audit_report: AuditReport | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "procedure_version": PROCEDURE_VERSION,
        "operator": "",
        "environment": "",
        "created_at": "",
        "legacy": {
            "database_url_env": "LEGACY_DATABASE_URL",
            "dump_path": "",
            "dump_sha256": "",
            "dump_size_bytes": "",
        },
        "target": {
            "database_url_env": "TARGET_DATABASE_URL or DATABASE_URL",
            "dump_path_before_import": "",
            "dump_sha256_before_import": "",
            "dump_size_bytes_before_import": "",
            "django_migration_state": "",
        },
        "approval": {
            "approved_by": "",
            "approved_at": "",
            "author_policy": "",
            "allow_non_empty_target": False,
            "accepted_warnings": [],
        },
        "audit": {
            "status": audit_report.status if audit_report else "",
            "legacy_database": audit_report.legacy_database if audit_report else "",
            "target_database": audit_report.target_database if audit_report else "",
            "report_path": "",
        },
        "phases": [
            {
                "key": phase.key,
                "title": phase.title,
                "status": "pending",
                "started_at": "",
                "finished_at": "",
                "rows_imported": {},
                "accepted_warnings": [],
                "validation_evidence": [],
                "rollback_reference": "",
                "notes": "",
            }
            for phase in MIGRATION_PHASES
        ],
        "final_validation": {
            "audit_status": "",
            "tests": [],
            "sequence_sync": "",
            "search_rebuild": "",
            "signoff": "",
        },
    }


def build_procedure_dict(audit_report: AuditReport | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "procedure_version": PROCEDURE_VERSION,
        "purpose": "Controlled legacy source to current Archetype schema migration procedure.",
        "artifacts": [
            "docs/database-map.md",
            "docs/legacy-migration-plan.md",
            "docs/legacy-migration-audit.md",
            "apps/common/legacy_migration_audit.py",
            "apps/common/legacy_migration_procedure.py",
            "apps/common/legacy_migration_importer.py",
        ],
        "safety_gates": [
            {
                "key": gate.key,
                "title": gate.title,
                "rule": gate.rule,
                "evidence": gate.evidence,
            }
            for gate in SAFETY_GATES
        ],
        "phases": [
            {
                "key": phase.key,
                "title": phase.title,
                "objective": phase.objective,
                "source_tables": list(phase.source_tables),
                "target_tables": list(phase.target_tables),
                "importer_contract": list(phase.importer_contract),
                "validation": list(phase.validation),
                "rollback": phase.rollback,
            }
            for phase in MIGRATION_PHASES
        ],
        "commands": [{"title": title, "command": command} for title, command in COMMANDS],
        "manifest_template": build_manifest_template(audit_report),
    }
    if audit_report:
        data["live_audit"] = report_to_dict(audit_report)
    return data


def render_procedure_json(audit_report: AuditReport | None = None) -> str:
    return json.dumps(build_procedure_dict(audit_report), indent=2, sort_keys=True, default=str) + "\n"


def render_manifest_template(audit_report: AuditReport | None = None) -> str:
    return json.dumps(build_manifest_template(audit_report), indent=2, sort_keys=True, default=str) + "\n"


def render_procedure_markdown(audit_report: AuditReport | None = None) -> str:
    lines = [
        "# Legacy Migration Operator Guide",
        "",
        f"Procedure version: `{PROCEDURE_VERSION}`",
        "",
        "This is the operational wrapper around the database map, migration plan, and read-only audit. "
        "It is designed for deployment runbooks, safe trial imports, and final migration evidence.",
        "",
        "The current safe position is deliberate: generate instructions, run preflight checks, plan the import, "
        "write a manifest, execute only with explicit flags, and audit the result.",
        "",
        "## Source Artifacts",
        "",
        "- `docs/database-map.md`: target schema map and current row counts.",
        "- `docs/legacy-migration-plan.md`: mapping policy and risk notes.",
        "- `docs/legacy-migration-audit.md`: checked-in live comparison snapshot.",
        "- `apps/common/legacy_migration_audit.py`: read-only audit/check engine.",
        "- `apps/common/legacy_migration_procedure.py`: this operator procedure definition.",
        "- `apps/common/legacy_migration_importer.py`: guarded write importer used by `migrate_legacy_data`.",
        "",
    ]

    if audit_report:
        lines.extend(
            [
                "## Live Audit Summary",
                "",
                f"- Status: `{audit_report.status}`",
                f"- Legacy database: `{audit_report.legacy_database}` ({audit_report.legacy_table_count} tables)",
                f"- Target database: `{audit_report.target_database}` ({audit_report.target_table_count} tables)",
                "",
            ]
        )

    lines.extend(
        [
            "## Deployment Rule",
            "",
            "This migration should be a manual deployment lane, not an automatic step on every deploy. "
            "The automatic deploy can run tests and the read-only audit; the write importer should require "
            "explicit environment variables, approvals, backups, and a filled manifest.",
            "",
            "## Safety Gates",
            "",
            "| Gate | Rule | Evidence |",
            "| --- | --- | --- |",
        ]
    )
    for gate in SAFETY_GATES:
        lines.append(f"| {gate.title} | {gate.rule} | {gate.evidence} |")

    lines.extend(
        [
            "",
            "## Phase Overview",
            "",
            "| Phase | Objective | Source | Target |",
            "| --- | --- | --- | --- |",
        ]
    )
    for phase in MIGRATION_PHASES:
        lines.append(
            f"| `{phase.key}` {phase.title} | {phase.objective} | "
            f"{', '.join(phase.source_tables)} | {', '.join(phase.target_tables)} |"
        )

    lines.extend(["", "## Phase Details", ""])
    for phase in MIGRATION_PHASES:
        lines.extend(
            [
                f"### `{phase.key}` {phase.title}",
                "",
                phase.objective,
                "",
                "Importer contract:",
            ]
        )
        lines.extend([f"- {item}" for item in phase.importer_contract])
        lines.append("")
        lines.append("Validation:")
        lines.extend([f"- {item}" for item in phase.validation])
        lines.extend(["", f"Rollback: {phase.rollback}", ""])

    lines.extend(
        [
            "## Deployment Integration",
            "",
            "- CI should run unit tests for the audit/procedure modules.",
            "- Pre-cutover should run `audit_legacy_migration`; fail status blocks the deployment.",
            "- Warning status requires a human to list accepted warnings in the manifest.",
            "- `migrate_legacy_data` plans by default and writes only with `--execute`.",
            "- The write import should run against a freshly migrated target unless "
            "`--allow-non-empty-target` is explicitly approved.",
            "- Post-cutover should run sequence sync, focused tests, smoke checks, and search rebuild.",
            "",
            "## Command Reference",
            "",
        ]
    )
    for title, command in COMMANDS:
        lines.extend([f"### {title}", "", "```bash", command, "```", ""])

    lines.extend(
        [
            "## Manifest",
            "",
            "Use `docs/legacy-migration-manifest-template.json` as the starting point for a real migration run. "
            "The completed manifest is the audit trail for backups, approvals, accepted warnings, phase results, "
            "validation evidence, and rollback references.",
            "",
            "## Write Importer",
            "",
            "Plan first. This connects to both databases and returns expected row counts without writing:",
            "",
            "```bash",
            "docker compose run --rm api python manage.py migrate_legacy_data \\",
            '  --legacy-url "$LEGACY_DATABASE_URL" \\',
            '  --target-url "$TARGET_DATABASE_URL" \\',
            "  --manifest /app/storage/legacy-migration-import-dry-run.json",
            "```",
            "",
            "Execute only against a backed-up, freshly migrated target database:",
            "",
            "```bash",
            "docker compose run --rm api python manage.py migrate_legacy_data --execute \\",
            '  --legacy-url "$LEGACY_DATABASE_URL" \\',
            '  --target-url "$TARGET_DATABASE_URL" \\',
            "  --publication-author-username <target-author-username> \\",
            "  --allow-warnings \\",
            "  --manifest /app/storage/legacy-migration-import-run.json",
            "```",
            "",
            "The command refuses same-database URLs, missing tables, and non-empty import targets by default. "
            "Use `--allow-non-empty-target` only for an approved recovery or incremental trial.",
        ]
    )

    return "\n".join(lines).rstrip() + "\n"
