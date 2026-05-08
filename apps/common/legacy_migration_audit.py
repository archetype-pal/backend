from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import re
from typing import Any

import psycopg
from psycopg import Connection, sql
from psycopg.rows import dict_row

DEFAULT_LEGACY_URL = "postgresql://postgres:password@postgres:5432/old_arch"
DEFAULT_TARGET_URL = "postgresql://postgres:password@postgres:5432/test_db"

TABLE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class LegacyMigrationAuditError(RuntimeError):
    pass


@dataclass(frozen=True)
class EntityMapping:
    key: str
    title: str
    legacy_table: str | None
    target_table: str
    category: str
    strategy: str
    notes: str
    strict_ids: bool = True
    legacy_count_sql: str | None = None
    target_count_sql: str | None = None
    legacy_ids_sql: str | None = None
    target_ids_sql: str | None = None
    allowed_extra_target_ids: frozenset[int] = field(default_factory=frozenset)
    allowed_missing_target_ids: frozenset[int] = field(default_factory=frozenset)


@dataclass(frozen=True)
class IdComparison:
    legacy_count: int
    target_count: int
    common_count: int
    missing_in_target_count: int
    extra_in_target_count: int
    unexpected_missing_count: int
    unexpected_extra_count: int
    missing_sample: list[int]
    extra_sample: list[int]


@dataclass(frozen=True)
class MappingResult:
    key: str
    title: str
    category: str
    strategy: str
    status: str
    legacy_count: int
    target_count: int
    notes: str
    id_comparison: IdComparison | None


@dataclass(frozen=True)
class CheckResult:
    key: str
    title: str
    status: str
    summary: str
    details: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class AuditReport:
    legacy_database: str
    target_database: str
    legacy_table_count: int
    target_table_count: int
    mappings: list[MappingResult]
    checks: list[CheckResult]

    @property
    def status(self) -> str:
        statuses = [result.status for result in [*self.mappings, *self.checks]]
        if "fail" in statuses:
            return "fail"
        if "warn" in statuses:
            return "warn"
        return "ok"


ENTITY_MAPPINGS: tuple[EntityMapping, ...] = (
    EntityMapping(
        key="dates",
        title="Dates",
        legacy_table="digipal_date",
        target_table="common_date",
        category="common",
        strategy="id-preserved",
        notes="Legacy sortable dates map directly to common.Date.",
    ),
    EntityMapping(
        key="item_formats",
        title="Item formats",
        legacy_table="digipal_format",
        target_table="manuscripts_itemformat",
        category="manuscripts",
        strategy="id-preserved",
        notes="Legacy formats map directly to ItemFormat.",
    ),
    EntityMapping(
        key="bibliographic_sources",
        title="Bibliographic sources",
        legacy_table="digipal_source",
        target_table="manuscripts_bibliographicsource",
        category="manuscripts",
        strategy="id-preserved",
        notes="Legacy sources map to BibliographicSource.",
    ),
    EntityMapping(
        key="repositories",
        title="Repositories",
        legacy_table="digipal_repository",
        target_table="manuscripts_repository",
        category="manuscripts",
        strategy="id-preserved transformed fields",
        notes="Place/type labels are denormalised in the target. Blank labels need explicit fallback labels.",
    ),
    EntityMapping(
        key="current_items",
        title="Current items",
        legacy_table="digipal_currentitem",
        target_table="manuscripts_currentitem",
        category="manuscripts",
        strategy="id-preserved transformed fields",
        notes="Shelfmark width is reduced in the target; validate truncation before applying a fresh import.",
    ),
    EntityMapping(
        key="historical_items",
        title="Historical items",
        legacy_table="digipal_historicalitem",
        target_table="manuscripts_historicalitem",
        category="manuscripts",
        strategy="id-preserved transformed lookups",
        notes="Legacy type/language/hair/date lookup data is flattened into target fields.",
    ),
    EntityMapping(
        key="historical_item_descriptions",
        title="Historical item descriptions",
        legacy_table="digipal_description",
        target_table="manuscripts_historicalitemdescription",
        category="manuscripts",
        strategy="id-preserved transformed fields",
        notes="Legacy description.description maps to target content.",
    ),
    EntityMapping(
        key="catalogue_numbers",
        title="Catalogue numbers",
        legacy_table="digipal_cataloguenumber",
        target_table="manuscripts_cataloguenumber",
        category="manuscripts",
        strategy="id-preserved transformed fields",
        notes="Legacy source_id maps to catalogue_id.",
    ),
    EntityMapping(
        key="item_parts",
        title="Item parts",
        legacy_table="digipal_itempart",
        target_table="manuscripts_itempart",
        category="manuscripts",
        strategy="id-preserved with placeholder",
        notes="The target has a synthetic -1 placeholder part; historical linkage comes from digipal_itempartitem.",
        allowed_extra_target_ids=frozenset({-1}),
    ),
    EntityMapping(
        key="item_images",
        title="Item images",
        legacy_table="digipal_image",
        target_table="manuscripts_itemimage",
        category="manuscripts",
        strategy="id-preserved transformed fields",
        notes="Legacy iipimage/image fields map into the IIIF-backed image field.",
    ),
    EntityMapping(
        key="image_texts",
        title="Image texts",
        legacy_table=None,
        target_table="manuscripts_imagetext",
        category="manuscripts",
        strategy="content-preserved, ids not preserved",
        notes=(
            "Non-empty legacy TextContentXML rows map to ImageText; empty draft translation/transcription rows "
            "are excluded."
        ),
        strict_ids=False,
        legacy_count_sql=(
            "SELECT count(*) "
            "FROM digipal_text_textcontentxml x "
            "WHERE x.content IS NOT NULL AND btrim(x.content) <> ''"
        ),
    ),
    EntityMapping(
        key="scribes",
        title="Scribes",
        legacy_table="digipal_scribe",
        target_table="scribes_scribe",
        category="scribes",
        strategy="id-preserved with placeholder",
        notes="The target has a synthetic -1 scribe for unmapped/unknown data.",
        allowed_extra_target_ids=frozenset({-1}),
    ),
    EntityMapping(
        key="scripts",
        title="Scripts",
        legacy_table="digipal_script",
        target_table="scribes_script",
        category="scribes",
        strategy="id-preserved",
        notes="No script rows are present in the inspected legacy dataset.",
    ),
    EntityMapping(
        key="hands",
        title="Hands",
        legacy_table="digipal_hand",
        target_table="scribes_hand",
        category="scribes",
        strategy="id-preserved transformed fields",
        notes="Legacy labels/display notes collapse into target name/place/description fields.",
    ),
    EntityMapping(
        key="hand_images",
        title="Hand image links",
        legacy_table="digipal_hand_images",
        target_table="scribes_hand_item_part_images",
        category="scribes",
        strategy="id-preserved",
        notes="Legacy hand/image many-to-many table maps directly.",
    ),
    EntityMapping(
        key="characters",
        title="Characters",
        legacy_table="digipal_character",
        target_table="symbols_structure_character",
        category="symbols",
        strategy="id-preserved transformed type",
        notes="Legacy ontograph/form data is flattened into the target type field.",
    ),
    EntityMapping(
        key="allographs",
        title="Allographs",
        legacy_table="digipal_allograph",
        target_table="symbols_structure_allograph",
        category="symbols",
        strategy="id-preserved with placeholder",
        notes="The target has a synthetic -1 allograph for text/unmapped annotations.",
        allowed_extra_target_ids=frozenset({-1}),
    ),
    EntityMapping(
        key="components",
        title="Components",
        legacy_table="digipal_component",
        target_table="symbols_structure_component",
        category="symbols",
        strategy="id-preserved",
        notes="Direct vocabulary mapping.",
    ),
    EntityMapping(
        key="features",
        title="Features",
        legacy_table="digipal_feature",
        target_table="symbols_structure_feature",
        category="symbols",
        strategy="id-preserved",
        notes="Direct vocabulary mapping.",
    ),
    EntityMapping(
        key="component_features",
        title="Component feature links",
        legacy_table="digipal_component_features",
        target_table="symbols_structure_component_features",
        category="symbols",
        strategy="id-preserved",
        notes="Component-level feature vocabulary links are preserved.",
    ),
    EntityMapping(
        key="allograph_components",
        title="Allograph components",
        legacy_table="digipal_allographcomponent",
        target_table="symbols_structure_allographcomponent",
        category="symbols",
        strategy="id-preserved with one omitted duplicate/stale row",
        notes="One legacy row is absent in the inspected target.",
        allowed_missing_target_ids=frozenset({46}),
    ),
    EntityMapping(
        key="allograph_component_features",
        title="Allograph component feature links",
        legacy_table="digipal_allographcomponent_features",
        target_table="symbols_structure_allographcomponentfeature",
        category="symbols",
        strategy="id-preserved with one omitted duplicate/stale row",
        notes="One legacy row is absent in the inspected target.",
        allowed_missing_target_ids=frozenset({127}),
    ),
    EntityMapping(
        key="positions",
        title="Positions",
        legacy_table="digipal_aspect",
        target_table="symbols_structure_position",
        category="symbols",
        strategy="id-preserved rename",
        notes="Legacy aspects become target positions.",
    ),
    EntityMapping(
        key="allograph_positions",
        title="Allograph position links",
        legacy_table="digipal_allograph_aspects",
        target_table="symbols_structure_allographposition",
        category="symbols",
        strategy="ids not preserved",
        notes="Legacy allograph/aspect links are re-keyed in the target.",
        strict_ids=False,
    ),
    EntityMapping(
        key="annotations",
        title="Annotations",
        legacy_table="digipal_annotation",
        target_table="annotations_graph",
        category="annotations",
        strategy="annotation ids preserved with six target extras",
        notes=(
            "Legacy annotations become target Graph rows. Image annotations join through digipal_graph; "
            "text/editorial rows remain annotation-like."
        ),
        allowed_extra_target_ids=frozenset({27321, 27328, 27329, 27331, 27332, 27333}),
    ),
    EntityMapping(
        key="graph_components",
        title="Graph components",
        legacy_table="digipal_graphcomponent",
        target_table="annotations_graphcomponent",
        category="annotations",
        strategy="mostly id-preserved, filtered",
        notes="Rows tied to omitted/legacy-only graph material are not fully represented.",
        strict_ids=False,
    ),
    EntityMapping(
        key="graph_component_features",
        title="Graph component feature links",
        legacy_table="digipal_graphcomponent_features",
        target_table="annotations_graphcomponent_features",
        category="annotations",
        strategy="mostly id-preserved, filtered",
        notes="Tracks the graph component filtering.",
        strict_ids=False,
    ),
    EntityMapping(
        key="graph_positions",
        title="Graph position links",
        legacy_table="digipal_graph_aspects",
        target_table="annotations_graph_positions",
        category="annotations",
        strategy="ids not preserved, one row omitted",
        notes="Legacy graph aspects become target graph positions and are re-keyed.",
        strict_ids=False,
    ),
    EntityMapping(
        key="publications",
        title="Publications",
        legacy_table="blog_blogpost",
        target_table="publications_publication",
        category="publications",
        strategy="id-preserved transformed fields",
        notes="Blog posts become publications. Author ids require special handling; see custom checks.",
    ),
    EntityMapping(
        key="publication_keywords",
        title="Publication keyword links",
        legacy_table="blog_blogpost_categories",
        target_table="publications_publication_keywords",
        category="publications",
        strategy="ids not preserved",
        notes="Legacy blog categories/keywords become tagulous publication keywords.",
        strict_ids=False,
    ),
    EntityMapping(
        key="carousel_items",
        title="Carousel items",
        legacy_table="digipal_carouselitem",
        target_table="publications_carouselitem",
        category="publications",
        strategy="id-preserved transformed fields",
        notes="Legacy sort_order/link/image fields map to target ordering/url/image.",
    ),
)


def legacy_url_from_env() -> str:
    return os.environ.get("LEGACY_DATABASE_URL", DEFAULT_LEGACY_URL)


def target_url_from_env() -> str:
    return os.environ.get("TARGET_DATABASE_URL", DEFAULT_TARGET_URL)


def _validate_table_name(table_name: str) -> None:
    if not TABLE_NAME_RE.fullmatch(table_name):
        raise LegacyMigrationAuditError(f"Unsafe or unsupported table name: {table_name!r}")


def _count_sql(table_name: str) -> sql.Composed:
    _validate_table_name(table_name)
    return sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table_name))


def _ids_sql(table_name: str) -> sql.Composed:
    _validate_table_name(table_name)
    return sql.SQL("SELECT id FROM {} ORDER BY id").format(sql.Identifier(table_name))


def _scalar(conn: Connection[Any], query: str | sql.Composed) -> Any:
    with conn.cursor() as cursor:
        cursor.execute(query)
        row = cursor.fetchone()
    if row is None:
        raise LegacyMigrationAuditError("Expected one row but query returned none")
    return row[0]


def _dict_rows(conn: Connection[Any], query: str | sql.Composed) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(query)
        return list(cursor.fetchall())


def _id_set(conn: Connection[Any], query: str | sql.Composed) -> set[int]:
    with conn.cursor() as cursor:
        cursor.execute(query)
        return {int(row[0]) for row in cursor.fetchall()}


def compare_id_sets(
    legacy_ids: set[int],
    target_ids: set[int],
    *,
    allowed_extra_target_ids: set[int] | frozenset[int] = frozenset(),
    allowed_missing_target_ids: set[int] | frozenset[int] = frozenset(),
    sample_size: int = 10,
) -> IdComparison:
    missing = legacy_ids - target_ids
    extra = target_ids - legacy_ids
    unexpected_missing = missing - set(allowed_missing_target_ids)
    unexpected_extra = extra - set(allowed_extra_target_ids)
    return IdComparison(
        legacy_count=len(legacy_ids),
        target_count=len(target_ids),
        common_count=len(legacy_ids & target_ids),
        missing_in_target_count=len(missing),
        extra_in_target_count=len(extra),
        unexpected_missing_count=len(unexpected_missing),
        unexpected_extra_count=len(unexpected_extra),
        missing_sample=sorted(missing)[:sample_size],
        extra_sample=sorted(extra)[:sample_size],
    )


def configure_read_only_session(conn: Connection[Any]) -> None:
    conn.autocommit = True
    conn.execute("SET default_transaction_read_only = on")
    conn.autocommit = False


def _mapping_status(
    mapping: EntityMapping,
    comparison: IdComparison | None,
    legacy_count: int,
    target_count: int,
) -> str:
    if comparison:
        if comparison.unexpected_missing_count or comparison.unexpected_extra_count:
            return "fail" if mapping.strict_ids else "warn"
        if comparison.missing_in_target_count or comparison.extra_in_target_count:
            return "warn"
        return "ok"

    if legacy_count == target_count:
        return "ok"
    return "warn"


def audit_mapping(legacy_conn: Connection[Any], target_conn: Connection[Any], mapping: EntityMapping) -> MappingResult:
    legacy_count_query = mapping.legacy_count_sql or _count_sql(mapping.legacy_table or "")
    target_count_query = mapping.target_count_sql or _count_sql(mapping.target_table)
    legacy_count = int(_scalar(legacy_conn, legacy_count_query))
    target_count = int(_scalar(target_conn, target_count_query))

    comparison = None
    if mapping.strict_ids or mapping.legacy_ids_sql or mapping.target_ids_sql:
        if mapping.legacy_table is None and mapping.legacy_ids_sql is None:
            raise LegacyMigrationAuditError(f"{mapping.key} asks for id comparison but has no legacy table/sql")
        legacy_ids = _id_set(legacy_conn, mapping.legacy_ids_sql or _ids_sql(mapping.legacy_table or ""))
        target_ids = _id_set(target_conn, mapping.target_ids_sql or _ids_sql(mapping.target_table))
        comparison = compare_id_sets(
            legacy_ids,
            target_ids,
            allowed_extra_target_ids=mapping.allowed_extra_target_ids,
            allowed_missing_target_ids=mapping.allowed_missing_target_ids,
        )

    return MappingResult(
        key=mapping.key,
        title=mapping.title,
        category=mapping.category,
        strategy=mapping.strategy,
        status=_mapping_status(mapping, comparison, legacy_count, target_count),
        legacy_count=legacy_count,
        target_count=target_count,
        notes=mapping.notes,
        id_comparison=comparison,
    )


def database_name(conn: Connection[Any]) -> str:
    return str(_scalar(conn, "SELECT current_database()"))


def public_table_count(conn: Connection[Any]) -> int:
    return int(
        _scalar(
            conn,
            (
                "SELECT count(*) "
                "FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
            ),
        )
    )


def require_tables(conn: Connection[Any], tables: set[str], *, database_label: str) -> None:
    rows = _dict_rows(
        conn,
        (
            "SELECT table_name "
            "FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        ),
    )
    present = {str(row["table_name"]) for row in rows}
    missing = sorted(tables - present)
    if missing:
        raise LegacyMigrationAuditError(f"{database_label} is missing required tables: {', '.join(missing)}")


def check_publication_author_mapping(legacy_conn: Connection[Any], target_conn: Connection[Any]) -> CheckResult:
    legacy_rows = _dict_rows(
        legacy_conn,
        """
        SELECT b.user_id AS id, u.username, count(*) AS post_count
        FROM blog_blogpost b
        JOIN auth_user u ON u.id = b.user_id
        GROUP BY b.user_id, u.username
        ORDER BY b.user_id
        """,
    )
    target_rows = _dict_rows(
        target_conn,
        """
        SELECT p.author_id AS id, u.username, count(*) AS post_count
        FROM publications_publication p
        JOIN auth_user u ON u.id = p.author_id
        GROUP BY p.author_id, u.username
        ORDER BY p.author_id
        """,
    )
    target_by_id = {row["id"]: row for row in target_rows}
    mismatches: list[dict[str, Any]] = []
    for legacy_row in legacy_rows:
        target_row = target_by_id.get(legacy_row["id"])
        if not target_row:
            mismatches.append(
                {
                    "legacy_id": legacy_row["id"],
                    "legacy_username": legacy_row["username"],
                    "target_username": None,
                    "post_count": legacy_row["post_count"],
                }
            )
            continue
        if target_row["username"] != legacy_row["username"]:
            mismatches.append(
                {
                    "legacy_id": legacy_row["id"],
                    "legacy_username": legacy_row["username"],
                    "target_username": target_row["username"],
                    "post_count": legacy_row["post_count"],
                }
            )

    if mismatches:
        return CheckResult(
            key="publication_author_mapping",
            title="Publication author mapping",
            status="warn",
            summary=(
                "Publication author ids are not a safe migration key because target users were seeded before "
                "legacy users. Map authors by username/email or choose an explicit fallback author."
            ),
            details=mismatches,
        )

    return CheckResult(
        key="publication_author_mapping",
        title="Publication author mapping",
        status="ok",
        summary="Publication author ids resolve to matching usernames.",
    )


def check_annotation_shape(legacy_conn: Connection[Any], target_conn: Connection[Any]) -> CheckResult:
    rows = _dict_rows(
        legacy_conn,
        """
        SELECT
          count(*) AS annotation_total,
          count(*) FILTER (WHERE graph_id IS NOT NULL) AS image_like_annotations,
          count(*) FILTER (WHERE graph_id IS NULL AND type = 'text') AS text_annotations,
          count(*) FILTER (WHERE graph_id IS NULL AND type = 'editorial') AS editorial_annotations
        FROM digipal_annotation
        """,
    )
    target_rows = _dict_rows(
        target_conn,
        """
        SELECT
          count(*) AS graph_total,
          count(*) FILTER (WHERE annotation_type = 'image') AS image_graphs,
          count(*) FILTER (WHERE annotation_type = 'text') AS text_graphs,
          count(*) FILTER (WHERE annotation_type = 'editorial') AS editorial_graphs,
          count(*) FILTER (
            WHERE annotation_type = 'image' AND (allograph_id IS NULL OR hand_id IS NULL)
          ) AS image_graphs_missing_required_fk,
          count(*) FILTER (
            WHERE annotation_type IN ('text', 'editorial') AND (allograph_id IS NOT NULL OR hand_id IS NOT NULL)
          ) AS non_image_graphs_with_legacy_fk
        FROM annotations_graph
        """,
    )
    details = [{**rows[0], **target_rows[0]}]
    if target_rows[0]["image_graphs_missing_required_fk"]:
        return CheckResult(
            key="annotation_shape",
            title="Annotation shape",
            status="fail",
            summary="Some target image annotations are missing allograph or hand links.",
            details=details,
        )
    if target_rows[0]["non_image_graphs_with_legacy_fk"]:
        return CheckResult(
            key="annotation_shape",
            title="Annotation shape",
            status="warn",
            summary=(
                "Target text/editorial annotations retain allograph/hand values. This is valid under the current "
                "database constraint but differs from the model comment that treats those links as optional."
            ),
            details=details,
        )
    return CheckResult(
        key="annotation_shape",
        title="Annotation shape",
        status="ok",
        summary="Target annotation shape matches expected graph/type constraints.",
        details=details,
    )


def check_legacy_text_exclusions(legacy_conn: Connection[Any], target_conn: Connection[Any]) -> CheckResult:
    details = _dict_rows(
        legacy_conn,
        """
        SELECT
          s.slug AS status,
          t.slug AS type,
          count(*) AS rows,
          count(*) FILTER (WHERE x.content IS NULL OR btrim(x.content) = '') AS empty_rows
        FROM digipal_text_textcontentxml x
        JOIN digipal_text_textcontentxmlstatus s ON s.id = x.status_id
        JOIN digipal_text_textcontent c ON c.id = x.text_content_id
        JOIN digipal_text_textcontenttype t ON t.id = c.type_id
        GROUP BY s.slug, t.slug
        ORDER BY t.slug, s.slug
        """,
    )
    legacy_non_empty = int(
        _scalar(
            legacy_conn,
            "SELECT count(*) FROM digipal_text_textcontentxml WHERE content IS NOT NULL AND btrim(content) <> ''",
        )
    )
    target_count = int(_scalar(target_conn, _count_sql("manuscripts_imagetext")))
    status = "ok" if legacy_non_empty == target_count else "warn"
    return CheckResult(
        key="legacy_text_exclusions",
        title="Legacy text exclusions",
        status=status,
        summary=f"Non-empty legacy text XML rows: {legacy_non_empty}; target ImageText rows: {target_count}.",
        details=details,
    )


def run_audit(legacy_url: str | None = None, target_url: str | None = None) -> AuditReport:
    legacy_url = legacy_url or legacy_url_from_env()
    target_url = target_url or target_url_from_env()

    try:
        legacy_conn = psycopg.connect(legacy_url)
        target_conn = psycopg.connect(target_url)
    except psycopg.Error as exc:
        raise LegacyMigrationAuditError(f"Could not connect to legacy/target databases: {exc}") from exc

    configure_read_only_session(legacy_conn)
    configure_read_only_session(target_conn)

    with legacy_conn, target_conn:
        legacy_db = database_name(legacy_conn)
        target_db = database_name(target_conn)
        if legacy_db == target_db:
            raise LegacyMigrationAuditError("Legacy and target database URLs point at the same database.")

        require_tables(
            legacy_conn,
            {"digipal_date", "digipal_annotation", "digipal_graph", "blog_blogpost"},
            database_label=f"legacy database {legacy_db}",
        )
        require_tables(
            target_conn,
            {"common_date", "annotations_graph", "manuscripts_historicalitem", "publications_publication"},
            database_label=f"target database {target_db}",
        )

        mappings = [audit_mapping(legacy_conn, target_conn, mapping) for mapping in ENTITY_MAPPINGS]
        checks = [
            check_publication_author_mapping(legacy_conn, target_conn),
            check_annotation_shape(legacy_conn, target_conn),
            check_legacy_text_exclusions(legacy_conn, target_conn),
        ]

        return AuditReport(
            legacy_database=legacy_db,
            target_database=target_db,
            legacy_table_count=public_table_count(legacy_conn),
            target_table_count=public_table_count(target_conn),
            mappings=mappings,
            checks=checks,
        )


def report_to_dict(report: AuditReport) -> dict[str, Any]:
    def id_comparison_to_dict(comparison: IdComparison | None) -> dict[str, Any] | None:
        if comparison is None:
            return None
        return {
            "legacy_count": comparison.legacy_count,
            "target_count": comparison.target_count,
            "common_count": comparison.common_count,
            "missing_in_target_count": comparison.missing_in_target_count,
            "extra_in_target_count": comparison.extra_in_target_count,
            "unexpected_missing_count": comparison.unexpected_missing_count,
            "unexpected_extra_count": comparison.unexpected_extra_count,
            "missing_sample": comparison.missing_sample,
            "extra_sample": comparison.extra_sample,
        }

    return {
        "status": report.status,
        "legacy_database": report.legacy_database,
        "target_database": report.target_database,
        "legacy_table_count": report.legacy_table_count,
        "target_table_count": report.target_table_count,
        "mappings": [
            {
                "key": result.key,
                "title": result.title,
                "category": result.category,
                "strategy": result.strategy,
                "status": result.status,
                "legacy_count": result.legacy_count,
                "target_count": result.target_count,
                "notes": result.notes,
                "id_comparison": id_comparison_to_dict(result.id_comparison),
            }
            for result in report.mappings
        ],
        "checks": [
            {
                "key": check.key,
                "title": check.title,
                "status": check.status,
                "summary": check.summary,
                "details": check.details,
            }
            for check in report.checks
        ],
    }


def render_json(report: AuditReport) -> str:
    return json.dumps(report_to_dict(report), indent=2, sort_keys=True, default=str)


def render_markdown(report: AuditReport) -> str:
    lines = [
        "# Legacy Migration Audit",
        "",
        f"Status: `{report.status}`",
        "",
        "| Database | Public tables |",
        "| --- | ---: |",
        f"| `{report.legacy_database}` | {report.legacy_table_count} |",
        f"| `{report.target_database}` | {report.target_table_count} |",
        "",
        "## Entity Mappings",
        "",
        "| Status | Entity | Legacy rows | Target rows | Strategy |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for result in report.mappings:
        lines.append(
            f"| `{result.status}` | {result.title} | {result.legacy_count} | "
            f"{result.target_count} | {result.strategy} |"
        )

    lines.extend(["", "## Checks", "", "| Status | Check | Summary |", "| --- | --- | --- |"])
    for check in report.checks:
        lines.append(f"| `{check.status}` | {check.title} | {check.summary} |")

    warnings = [result for result in report.mappings if result.status != "ok"]
    if warnings:
        lines.extend(["", "## Mapping Details", ""])
        for result in warnings:
            lines.extend(
                [
                    f"### {result.title}",
                    "",
                    f"- Status: `{result.status}`",
                    f"- Strategy: {result.strategy}",
                    f"- Notes: {result.notes}",
                ]
            )
            if result.id_comparison:
                comparison = result.id_comparison
                lines.extend(
                    [
                        f"- Missing in target: {comparison.missing_in_target_count}; sample: "
                        f"`{comparison.missing_sample}`",
                        f"- Extra in target: {comparison.extra_in_target_count}; sample: "
                        f"`{comparison.extra_sample}`",
                    ]
                )
            lines.append("")

    detailed_checks = [check for check in report.checks if check.status != "ok" and check.details]
    if detailed_checks:
        lines.extend(["", "## Check Details", ""])
        for check in detailed_checks:
            lines.extend([f"### {check.title}", "", f"{check.summary}", ""])
            lines.append("```json")
            lines.append(json.dumps(check.details, indent=2, sort_keys=True, default=str))
            lines.append("```")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"
