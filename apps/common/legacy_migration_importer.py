from __future__ import annotations

import ast
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
from pathlib import Path
import re
from typing import Any

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row

from apps.common.legacy_migration_audit import (
    LegacyMigrationAuditError,
    configure_read_only_session,
    database_name,
    legacy_url_from_env,
    report_to_dict,
    require_tables,
    run_audit,
    target_url_from_env,
)


class LegacyMigrationImportError(RuntimeError):
    pass


YEAR_RE = re.compile(r"(?<!\d)([1-2]\d{3}|[5-9]\d{2})(?!\d)")

PHASE_ORDER: tuple[str, ...] = (
    "core_vocabularies",
    "symbols",
    "manuscripts",
    "scribes_hands",
    "image_text",
    "annotations",
    "publications",
    "target_only",
)

REQUIRED_LEGACY_TABLES: set[str] = {
    "auth_user",
    "blog_blogcategory",
    "blog_blogpost",
    "blog_blogpost_categories",
    "digipal_allograph",
    "digipal_allograph_aspects",
    "digipal_allographcomponent",
    "digipal_allographcomponent_features",
    "digipal_annotation",
    "digipal_aspect",
    "digipal_carouselitem",
    "digipal_cataloguenumber",
    "digipal_character",
    "digipal_characterform",
    "digipal_component",
    "digipal_component_features",
    "digipal_currentitem",
    "digipal_date",
    "digipal_dateevidence",
    "digipal_description",
    "digipal_feature",
    "digipal_format",
    "digipal_graph",
    "digipal_graph_aspects",
    "digipal_graphcomponent",
    "digipal_graphcomponent_features",
    "digipal_hand",
    "digipal_hand_images",
    "digipal_hair",
    "digipal_historicalitem",
    "digipal_historicalitemtype",
    "digipal_idiograph",
    "digipal_image",
    "digipal_itempart",
    "digipal_itempartitem",
    "digipal_language",
    "digipal_ontograph",
    "digipal_place",
    "digipal_repository",
    "digipal_script",
    "digipal_source",
    "digipal_text_textcontent",
    "digipal_text_textcontenttype",
    "digipal_text_textcontentxml",
    "digipal_text_textcontentxmlstatus",
}

REQUIRED_TARGET_TABLES: set[str] = {
    "annotations_graph",
    "annotations_graph_positions",
    "annotations_graphcomponent",
    "annotations_graphcomponent_features",
    "auth_user",
    "common_date",
    "manuscripts_bibliographicsource",
    "manuscripts_cataloguenumber",
    "manuscripts_currentitem",
    "manuscripts_historicalitem",
    "manuscripts_historicalitemdescription",
    "manuscripts_imagetext",
    "manuscripts_itemformat",
    "manuscripts_itemimage",
    "manuscripts_itempart",
    "manuscripts_repository",
    "publications_carouselitem",
    "publications_publication",
    "publications_publication_keywords",
    "publications_tagulous_publication_keywords",
    "scribes_hand",
    "scribes_hand_item_part_images",
    "scribes_scribe",
    "scribes_script",
    "symbols_structure_allograph",
    "symbols_structure_allographcomponent",
    "symbols_structure_allographcomponentfeature",
    "symbols_structure_allographposition",
    "symbols_structure_character",
    "symbols_structure_component",
    "symbols_structure_component_features",
    "symbols_structure_feature",
    "symbols_structure_position",
}

TARGET_DOMAIN_TABLES: tuple[str, ...] = (
    "common_date",
    "manuscripts_itemformat",
    "manuscripts_bibliographicsource",
    "manuscripts_repository",
    "manuscripts_currentitem",
    "manuscripts_historicalitem",
    "manuscripts_historicalitemdescription",
    "manuscripts_cataloguenumber",
    "manuscripts_itempart",
    "manuscripts_itemimage",
    "manuscripts_imagetext",
    "scribes_scribe",
    "scribes_script",
    "scribes_hand",
    "scribes_hand_item_part_images",
    "symbols_structure_character",
    "symbols_structure_allograph",
    "symbols_structure_feature",
    "symbols_structure_component",
    "symbols_structure_component_features",
    "symbols_structure_allographcomponent",
    "symbols_structure_allographcomponentfeature",
    "symbols_structure_position",
    "symbols_structure_allographposition",
    "annotations_graph",
    "annotations_graphcomponent",
    "annotations_graphcomponent_features",
    "annotations_graph_positions",
    "publications_publication",
    "publications_publication_keywords",
    "publications_carouselitem",
    "publications_tagulous_publication_keywords",
)

SEQUENCE_TABLES: tuple[str, ...] = TARGET_DOMAIN_TABLES + (
    "publications_tagulous_publication_keywords",
    "publications_publication_keywords",
    "symbols_structure_allographposition",
    "annotations_graph_positions",
    "annotations_graphcomponent_features",
)

PHASE_TARGET_TABLES: dict[str, tuple[str, ...]] = {
    "core_vocabularies": (
        "common_date",
        "manuscripts_itemformat",
        "manuscripts_bibliographicsource",
        "manuscripts_repository",
    ),
    "symbols": (
        "symbols_structure_character",
        "symbols_structure_allograph",
        "symbols_structure_feature",
        "symbols_structure_component",
        "symbols_structure_component_features",
        "symbols_structure_allographcomponent",
        "symbols_structure_allographcomponentfeature",
        "symbols_structure_position",
        "symbols_structure_allographposition",
    ),
    "manuscripts": (
        "manuscripts_currentitem",
        "manuscripts_historicalitem",
        "manuscripts_historicalitemdescription",
        "manuscripts_cataloguenumber",
        "manuscripts_itempart",
        "manuscripts_itemimage",
    ),
    "scribes_hands": (
        "scribes_scribe",
        "scribes_script",
        "scribes_hand",
        "scribes_hand_item_part_images",
    ),
    "image_text": ("manuscripts_imagetext",),
    "annotations": (
        "annotations_graph",
        "annotations_graphcomponent",
        "annotations_graphcomponent_features",
        "annotations_graph_positions",
    ),
    "publications": (
        "publications_tagulous_publication_keywords",
        "publications_publication",
        "publications_publication_keywords",
        "publications_carouselitem",
    ),
    "target_only": (),
}

SOURCE_COUNT_SQL: dict[str, dict[str, str]] = {
    "core_vocabularies": {
        "common_date": "SELECT count(*) FROM digipal_date",
        "manuscripts_itemformat": "SELECT count(*) FROM digipal_format",
        "manuscripts_bibliographicsource": "SELECT count(*) FROM digipal_source",
        "manuscripts_repository": "SELECT count(*) FROM digipal_repository",
    },
    "symbols": {
        "symbols_structure_character": "SELECT count(*) FROM digipal_character",
        "symbols_structure_allograph": "SELECT count(*) + 1 FROM digipal_allograph",
        "symbols_structure_feature": "SELECT count(*) FROM digipal_feature",
        "symbols_structure_component": "SELECT count(*) FROM digipal_component",
        "symbols_structure_component_features": "SELECT count(*) FROM digipal_component_features",
        "symbols_structure_allographcomponent": "SELECT count(*) FROM digipal_allographcomponent WHERE id <> 46",
        "symbols_structure_allographcomponentfeature": (
            "SELECT count(*) FROM digipal_allographcomponent_features WHERE id <> 127"
        ),
        "symbols_structure_position": "SELECT count(*) FROM digipal_aspect",
        "symbols_structure_allographposition": "SELECT count(*) FROM digipal_allograph_aspects",
    },
    "manuscripts": {
        "manuscripts_currentitem": "SELECT count(*) FROM digipal_currentitem",
        "manuscripts_historicalitem": "SELECT count(*) FROM digipal_historicalitem",
        "manuscripts_historicalitemdescription": "SELECT count(*) FROM digipal_description",
        "manuscripts_cataloguenumber": (
            "SELECT count(*) FROM digipal_cataloguenumber WHERE historical_item_id IS NOT NULL"
        ),
        "manuscripts_itempart": (
            "SELECT count(*) + CASE WHEN EXISTS (SELECT 1 FROM digipal_image WHERE item_part_id IS NULL) "
            "THEN 1 ELSE 0 END FROM digipal_itempart"
        ),
        "manuscripts_itemimage": "SELECT count(*) FROM digipal_image",
    },
    "scribes_hands": {
        "scribes_scribe": "SELECT count(*) + 1 FROM digipal_scribe",
        "scribes_script": "SELECT count(*) FROM digipal_script",
        "scribes_hand": "SELECT count(*) FROM digipal_hand",
        "scribes_hand_item_part_images": "SELECT count(*) FROM digipal_hand_images",
    },
    "image_text": {
        "manuscripts_imagetext": (
            "SELECT count(*) FROM digipal_text_textcontentxml WHERE content IS NOT NULL AND btrim(content) <> ''"
        ),
    },
    "annotations": {
        "annotations_graph": "SELECT count(*) FROM digipal_annotation",
        "annotations_graphcomponent": (
            "SELECT count(*) FROM ("
            "SELECT DISTINCT ON (a.id, gc.component_id) gc.id "
            "FROM digipal_graphcomponent gc "
            "JOIN digipal_annotation a ON a.graph_id = gc.graph_id "
            "ORDER BY a.id, gc.component_id, gc.id"
            ") x"
        ),
        "annotations_graphcomponent_features": (
            "WITH mapped_gc AS ("
            "SELECT gc.id, min(gc.id) OVER (PARTITION BY a.id, gc.component_id) AS target_gc_id "
            "FROM digipal_graphcomponent gc JOIN digipal_annotation a ON a.graph_id = gc.graph_id"
            ") "
            "SELECT count(*) FROM ("
            "SELECT DISTINCT mg.target_gc_id, gcf.feature_id "
            "FROM digipal_graphcomponent_features gcf JOIN mapped_gc mg ON mg.id = gcf.graphcomponent_id"
            ") x"
        ),
        "annotations_graph_positions": (
            "SELECT count(*) FROM ("
            "SELECT DISTINCT a.id, ga.aspect_id "
            "FROM digipal_graph_aspects ga JOIN digipal_annotation a ON a.graph_id = ga.graph_id"
            ") x"
        ),
    },
    "publications": {
        "publications_tagulous_publication_keywords": "SELECT count(*) FROM blog_blogcategory",
        "publications_publication": "SELECT count(*) FROM blog_blogpost",
        "publications_publication_keywords": "SELECT count(*) FROM blog_blogpost_categories",
        "publications_carouselitem": "SELECT count(*) FROM digipal_carouselitem",
    },
    "target_only": {},
}


@dataclass(frozen=True)
class ImportOptions:
    legacy_url: str | None = None
    target_url: str | None = None
    phases: tuple[str, ...] = ("all",)
    execute: bool = False
    allow_non_empty_target: bool = False
    allow_warnings: bool = False
    publication_author_id: int | None = None
    publication_author_username: str | None = None
    skip_post_audit: bool = False
    manifest_path: Path | None = None


@dataclass
class PhaseResult:
    key: str
    status: str
    started_at: str
    finished_at: str
    rows_planned: dict[str, int] = field(default_factory=dict)
    rows_imported: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ImportReport:
    dry_run: bool
    legacy_database: str
    target_database: str
    phases: list[PhaseResult]
    target_row_counts_before: dict[str, int]
    target_row_counts_after: dict[str, int]
    audit: dict[str, Any] | None = None

    @property
    def status(self) -> str:
        if any(phase.status == "fail" for phase in self.phases):
            return "fail"
        if self.audit and self.audit.get("status") == "fail":
            return "fail"
        if any(phase.status == "warn" for phase in self.phases):
            return "warn"
        if self.audit and self.audit.get("status") == "warn":
            return "warn"
        return "ok"


class ImportContext:
    def __init__(self, legacy_conn: Connection[Any], target_conn: Connection[Any], options: ImportOptions) -> None:
        self.legacy_conn = legacy_conn
        self.target_conn = target_conn
        self.options = options


def utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def expand_phases(phases: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    requested = tuple(phases) or ("all",)
    if "all" in requested:
        if len(requested) > 1:
            raise LegacyMigrationImportError("--phase all cannot be combined with other phases")
        return PHASE_ORDER

    unknown = sorted(set(requested) - set(PHASE_ORDER))
    if unknown:
        raise LegacyMigrationImportError(f"Unknown migration phase(s): {', '.join(unknown)}")

    ordered = [phase for phase in PHASE_ORDER if phase in requested]
    return tuple(ordered)


def parse_date_weights(
    date_text: str | None, min_weight: Any = None, max_weight: Any = None, weight: Any = None
) -> tuple[int, int]:
    years = [int(value) for value in YEAR_RE.findall(date_text or "")]
    if years:
        return min(years), max(years)

    fallback_values = [min_weight, max_weight, weight]
    numeric = [int(value) for value in fallback_values if value is not None]
    if numeric:
        return min(numeric), max(numeric)

    return 0, 0


def legacy_image_path(iipimage: str | None, image: str | None = None) -> str:
    path = (iipimage or image or "").strip()
    if path.startswith("jp2/"):
        path = path[4:]
    if path.lower().endswith(".tif"):
        path = f"{path[:-4]}.jp2"
    return path


def parse_annotation(raw: str | dict[str, Any] | list[Any] | None) -> dict[str, Any] | list[Any]:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict | list):
        return raw
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        try:
            value = ast.literal_eval(raw)
        except SyntaxError, ValueError:
            return {"legacy_raw": raw}
    if isinstance(value, dict | list):
        return value
    return {"legacy_raw": raw}


def truncate(value: Any, max_length: int, default: str = "") -> str:
    text = default if value is None else str(value)
    return text[:max_length]


def text_or_blank(value: Any) -> str:
    return "" if value is None else str(value)


def choice_value(value: Any, *, max_length: int | None = None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    lowered = text.lower()
    return lowered[:max_length] if max_length else lowered


def fetch_rows(
    conn: Connection[Any], query: str, params: tuple[Any, ...] | dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(query, params)
        return list(cursor.fetchall())


def scalar(conn: Connection[Any], query: str, params: tuple[Any, ...] | dict[str, Any] | None = None) -> Any:
    with conn.cursor() as cursor:
        cursor.execute(query, params)
        row = cursor.fetchone()
    if row is None:
        raise LegacyMigrationImportError("Expected one row but query returned none")
    return row[0]


def insert_rows(conn: Connection[Any], query: str, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    with conn.cursor() as cursor:
        cursor.executemany(query, rows)
    return len(rows)


def target_domain_counts(conn: Connection[Any]) -> dict[str, int]:
    return {table: int(scalar(conn, f"SELECT count(*) FROM {table}")) for table in TARGET_DOMAIN_TABLES}


def phase_plan_counts(legacy_conn: Connection[Any], phase: str) -> dict[str, int]:
    return {table: int(scalar(legacy_conn, query)) for table, query in SOURCE_COUNT_SQL[phase].items()}


def assert_target_ready(counts: dict[str, int], phases: tuple[str, ...], *, allow_non_empty_target: bool) -> None:
    if allow_non_empty_target:
        return
    checked_tables = [table for phase in phases for table in PHASE_TARGET_TABLES[phase]]
    non_empty = {table: counts[table] for table in checked_tables if counts.get(table, 0)}
    if non_empty:
        formatted = ", ".join(f"{table}={count}" for table, count in sorted(non_empty.items()))
        raise LegacyMigrationImportError(
            "Target import tables are not empty. Refusing write import without --allow-non-empty-target. "
            f"Non-empty tables: {formatted}"
        )


def resolve_publication_author_id(conn: Connection[Any], *, author_id: int | None, username: str | None) -> int:
    if author_id is not None and username:
        raise LegacyMigrationImportError(
            "Use either --publication-author-id or --publication-author-username, not both"
        )
    if author_id is None and not username:
        raise LegacyMigrationImportError(
            "The publications phase requires --publication-author-id or --publication-author-username"
        )
    if author_id is not None:
        count = int(scalar(conn, "SELECT count(*) FROM auth_user WHERE id = %s", (author_id,)))
        if count != 1:
            raise LegacyMigrationImportError(f"No target auth_user found for id {author_id}")
        return author_id

    row_id = scalar(conn, "SELECT id FROM auth_user WHERE username = %s", (username,))
    return int(row_id)


def reset_sequences(conn: Connection[Any], tables: tuple[str, ...] = SEQUENCE_TABLES) -> int:
    reset_count = 0
    with conn.cursor() as cursor:
        for table in dict.fromkeys(tables):
            cursor.execute(
                """
                SELECT pg_get_serial_sequence(%s, 'id')
                """,
                (table,),
            )
            sequence_name = cursor.fetchone()[0]
            if not sequence_name:
                continue
            cursor.execute(
                f"""
                SELECT setval(%s, GREATEST(COALESCE((SELECT MAX(id) FROM {table}), 0), 1), true)
                """,
                (sequence_name,),
            )
            reset_count += 1
    return reset_count


def import_core_vocabularies(ctx: ImportContext) -> dict[str, int]:
    legacy_conn = ctx.legacy_conn
    target_conn = ctx.target_conn
    rows_imported: dict[str, int] = {}

    date_rows = fetch_rows(
        legacy_conn,
        """
        SELECT id, date, min_weight, max_weight, weight
        FROM digipal_date
        ORDER BY id
        """,
    )
    date_values = []
    for row in date_rows:
        min_weight, max_weight = parse_date_weights(row["date"], row["min_weight"], row["max_weight"], row["weight"])
        date_values.append(
            {"id": row["id"], "date": text_or_blank(row["date"]), "min_weight": min_weight, "max_weight": max_weight}
        )
    rows_imported["common_date"] = insert_rows(
        target_conn,
        """
        INSERT INTO common_date (id, date, min_weight, max_weight)
        VALUES (%(id)s, %(date)s, %(min_weight)s, %(max_weight)s)
        """,
        date_values,
    )

    format_rows = fetch_rows(legacy_conn, "SELECT id, name FROM digipal_format ORDER BY id")
    rows_imported["manuscripts_itemformat"] = insert_rows(
        target_conn,
        "INSERT INTO manuscripts_itemformat (id, name) VALUES (%(id)s, %(name)s)",
        [{"id": row["id"], "name": truncate(row["name"], 100)} for row in format_rows],
    )

    source_rows = fetch_rows(legacy_conn, "SELECT id, name, label FROM digipal_source ORDER BY id")
    rows_imported["manuscripts_bibliographicsource"] = insert_rows(
        target_conn,
        """
        INSERT INTO manuscripts_bibliographicsource (id, name, label)
        VALUES (%(id)s, %(name)s, %(label)s)
        """,
        [
            {
                "id": row["id"],
                "name": text_or_blank(row["name"]),
                "label": truncate(row["label"] or row["name"], 100),
            }
            for row in source_rows
        ],
    )

    repository_rows = fetch_rows(
        legacy_conn,
        """
        SELECT r.id, r.name, r.short_name, r.url, p.name AS place
        FROM digipal_repository r
        LEFT JOIN digipal_place p ON p.id = r.place_id
        ORDER BY r.id
        """,
    )
    repositories = []
    for row in repository_rows:
        label = truncate(row["short_name"] or row["name"] or f"repo-{row['id']}", 30)
        place = truncate(row["place"] or "", 50)
        repositories.append(
            {
                "id": row["id"],
                "name": truncate(row["name"] or label, 100),
                "label": label,
                "place": place,
                "url": row["url"] or None,
                "type": "library" if place and place.lower() != "unknown" else None,
            }
        )
    rows_imported["manuscripts_repository"] = insert_rows(
        target_conn,
        """
        INSERT INTO manuscripts_repository (id, name, label, place, url, type)
        VALUES (%(id)s, %(name)s, %(label)s, %(place)s, %(url)s, %(type)s)
        """,
        repositories,
    )
    return rows_imported


def import_symbols(ctx: ImportContext) -> dict[str, int]:
    legacy_conn = ctx.legacy_conn
    target_conn = ctx.target_conn
    rows_imported: dict[str, int] = {}

    character_rows = fetch_rows(
        legacy_conn,
        """
        SELECT c.id, c.name, cf.name AS form_name, o.name AS ontograph_name
        FROM digipal_character c
        LEFT JOIN digipal_characterform cf ON cf.id = c.form_id
        LEFT JOIN digipal_ontograph o ON o.id = c.ontograph_id
        ORDER BY c.id
        """,
    )
    rows_imported["symbols_structure_character"] = insert_rows(
        target_conn,
        """
        INSERT INTO symbols_structure_character (id, name, type)
        VALUES (%(id)s, %(name)s, %(type)s)
        """,
        [
            {
                "id": row["id"],
                "name": text_or_blank(row["name"]),
                "type": truncate(row["form_name"] or row["ontograph_name"] or "", 16) or None,
            }
            for row in character_rows
        ],
    )

    allograph_rows = fetch_rows(legacy_conn, "SELECT id, name, character_id FROM digipal_allograph ORDER BY id")
    allographs = [{"id": -1, "name": "unmapped_allographs", "character_id": 109}]
    allographs.extend(
        {"id": row["id"], "name": text_or_blank(row["name"]), "character_id": row["character_id"]}
        for row in allograph_rows
    )
    rows_imported["symbols_structure_allograph"] = insert_rows(
        target_conn,
        """
        INSERT INTO symbols_structure_allograph (id, name, character_id)
        VALUES (%(id)s, %(name)s, %(character_id)s)
        """,
        allographs,
    )

    feature_rows = fetch_rows(legacy_conn, "SELECT id, name FROM digipal_feature ORDER BY id")
    rows_imported["symbols_structure_feature"] = insert_rows(
        target_conn,
        "INSERT INTO symbols_structure_feature (id, name) VALUES (%(id)s, %(name)s)",
        [{"id": row["id"], "name": text_or_blank(row["name"])} for row in feature_rows],
    )

    component_rows = fetch_rows(legacy_conn, "SELECT id, name FROM digipal_component ORDER BY id")
    rows_imported["symbols_structure_component"] = insert_rows(
        target_conn,
        "INSERT INTO symbols_structure_component (id, name) VALUES (%(id)s, %(name)s)",
        [{"id": row["id"], "name": text_or_blank(row["name"])} for row in component_rows],
    )

    component_feature_rows = fetch_rows(
        legacy_conn,
        """
        SELECT id, component_id, feature_id
        FROM digipal_component_features
        ORDER BY id
        """,
    )
    rows_imported["symbols_structure_component_features"] = insert_rows(
        target_conn,
        """
        INSERT INTO symbols_structure_component_features (id, component_id, feature_id)
        VALUES (%(id)s, %(component_id)s, %(feature_id)s)
        """,
        component_feature_rows,
    )

    allograph_component_rows = fetch_rows(
        legacy_conn,
        """
        SELECT id, allograph_id, component_id
        FROM digipal_allographcomponent
        WHERE id <> 46
        ORDER BY id
        """,
    )
    rows_imported["symbols_structure_allographcomponent"] = insert_rows(
        target_conn,
        """
        INSERT INTO symbols_structure_allographcomponent (id, allograph_id, component_id)
        VALUES (%(id)s, %(allograph_id)s, %(component_id)s)
        """,
        allograph_component_rows,
    )

    allograph_component_feature_rows = fetch_rows(
        legacy_conn,
        """
        SELECT id, allographcomponent_id AS allograph_component_id, feature_id, false AS set_by_default
        FROM digipal_allographcomponent_features
        WHERE id <> 127
        ORDER BY id
        """,
    )
    rows_imported["symbols_structure_allographcomponentfeature"] = insert_rows(
        target_conn,
        """
        INSERT INTO symbols_structure_allographcomponentfeature (
          id, allograph_component_id, feature_id, set_by_default
        )
        VALUES (%(id)s, %(allograph_component_id)s, %(feature_id)s, %(set_by_default)s)
        """,
        allograph_component_feature_rows,
    )

    position_rows = fetch_rows(legacy_conn, "SELECT id, name FROM digipal_aspect ORDER BY id")
    rows_imported["symbols_structure_position"] = insert_rows(
        target_conn,
        "INSERT INTO symbols_structure_position (id, name) VALUES (%(id)s, %(name)s)",
        [{"id": row["id"], "name": text_or_blank(row["name"])} for row in position_rows],
    )

    allograph_position_rows = fetch_rows(
        legacy_conn,
        """
        SELECT allograph_id, aspect_id AS position_id
        FROM digipal_allograph_aspects
        ORDER BY allograph_id, aspect_id
        """,
    )
    rows_imported["symbols_structure_allographposition"] = insert_rows(
        target_conn,
        """
        INSERT INTO symbols_structure_allographposition (allograph_id, position_id)
        VALUES (%(allograph_id)s, %(position_id)s)
        """,
        allograph_position_rows,
    )
    return rows_imported


def import_manuscripts(ctx: ImportContext) -> dict[str, int]:
    legacy_conn = ctx.legacy_conn
    target_conn = ctx.target_conn
    rows_imported: dict[str, int] = {}

    current_item_rows = fetch_rows(
        legacy_conn,
        """
        SELECT id, repository_id, shelfmark, description
        FROM digipal_currentitem
        ORDER BY id
        """,
    )
    rows_imported["manuscripts_currentitem"] = insert_rows(
        target_conn,
        """
        INSERT INTO manuscripts_currentitem (id, repository_id, shelfmark, description)
        VALUES (%(id)s, %(repository_id)s, %(shelfmark)s, %(description)s)
        """,
        [
            {
                "id": row["id"],
                "repository_id": row["repository_id"],
                "shelfmark": truncate(row["shelfmark"], 60),
                "description": text_or_blank(row["description"]),
            }
            for row in current_item_rows
        ],
    )

    historical_item_rows = fetch_rows(
        legacy_conn,
        """
        WITH chosen_date AS (
          SELECT DISTINCT ON (historical_item_id)
            historical_item_id,
            date_id
          FROM digipal_dateevidence
          WHERE historical_item_id IS NOT NULL AND date_id IS NOT NULL
          ORDER BY historical_item_id, is_firm_date DESC, id
        )
        SELECT
          h.id,
          t.name AS type,
          h.historical_item_format_id AS format_id,
          l.name AS language,
          hair.label AS hair_type,
          cd.date_id
        FROM digipal_historicalitem h
        LEFT JOIN digipal_historicalitemtype t ON t.id = h.historical_item_type_id
        LEFT JOIN digipal_language l ON l.id = h.language_id
        LEFT JOIN digipal_hair hair ON hair.id = h.hair_id
        LEFT JOIN chosen_date cd ON cd.historical_item_id = h.id
        ORDER BY h.id
        """,
    )
    rows_imported["manuscripts_historicalitem"] = insert_rows(
        target_conn,
        """
        INSERT INTO manuscripts_historicalitem (id, type, format_id, language, hair_type, date_id)
        VALUES (%(id)s, %(type)s, %(format_id)s, %(language)s, %(hair_type)s, %(date_id)s)
        """,
        [
            {
                "id": row["id"],
                "type": choice_value(row["type"], max_length=20),
                "format_id": row["format_id"],
                "language": row["language"] or None,
                "hair_type": choice_value(row["hair_type"], max_length=20),
                "date_id": row["date_id"],
            }
            for row in historical_item_rows
        ],
    )

    description_rows = fetch_rows(
        legacy_conn,
        """
        SELECT id, historical_item_id, source_id, description AS content
        FROM digipal_description
        ORDER BY id
        """,
    )
    rows_imported["manuscripts_historicalitemdescription"] = insert_rows(
        target_conn,
        """
        INSERT INTO manuscripts_historicalitemdescription (id, historical_item_id, source_id, content)
        VALUES (%(id)s, %(historical_item_id)s, %(source_id)s, %(content)s)
        """,
        [
            {
                "id": row["id"],
                "historical_item_id": row["historical_item_id"],
                "source_id": row["source_id"],
                "content": text_or_blank(row["content"]),
            }
            for row in description_rows
        ],
    )

    catalogue_rows = fetch_rows(
        legacy_conn,
        """
        SELECT id, historical_item_id, source_id AS catalogue_id, number, url
        FROM digipal_cataloguenumber
        WHERE historical_item_id IS NOT NULL
        ORDER BY id
        """,
    )
    rows_imported["manuscripts_cataloguenumber"] = insert_rows(
        target_conn,
        """
        INSERT INTO manuscripts_cataloguenumber (id, historical_item_id, catalogue_id, number, url)
        VALUES (%(id)s, %(historical_item_id)s, %(catalogue_id)s, %(number)s, %(url)s)
        """,
        [
            {
                "id": row["id"],
                "historical_item_id": row["historical_item_id"],
                "catalogue_id": row["catalogue_id"],
                "number": truncate(row["number"], 30),
                "url": row["url"] or None,
            }
            for row in catalogue_rows
        ],
    )

    item_part_rows = fetch_rows(
        legacy_conn,
        """
        SELECT
          ip.id,
          ip.current_item_id,
          ip.custom_label,
          ip.locus AS item_part_locus,
          ipi.historical_item_id,
          ipi.locus AS item_link_locus
        FROM digipal_itempart ip
        JOIN digipal_itempartitem ipi ON ipi.item_part_id = ip.id
        ORDER BY ip.id
        """,
    )
    item_parts = [
        {
            "id": row["id"],
            "current_item_id": row["current_item_id"],
            "historical_item_id": row["historical_item_id"],
            "current_item_locus": truncate(row["item_link_locus"] or row["item_part_locus"] or "", 30),
            "custom_label": truncate(row["custom_label"] or "", 80),
        }
        for row in item_part_rows
    ]
    null_image_count = int(scalar(legacy_conn, "SELECT count(*) FROM digipal_image WHERE item_part_id IS NULL"))
    if null_image_count:
        item_parts.insert(
            0,
            {
                "id": -1,
                "current_item_id": 2,
                "historical_item_id": 1,
                "current_item_locus": "-public.manuscripts_itemimage",
                "custom_label": "Created for all the nulls contained in public.digipal_image ",
            },
        )
    rows_imported["manuscripts_itempart"] = insert_rows(
        target_conn,
        """
        INSERT INTO manuscripts_itempart (
          id, historical_item_id, custom_label, current_item_id, current_item_locus
        )
        VALUES (%(id)s, %(historical_item_id)s, %(custom_label)s, %(current_item_id)s, %(current_item_locus)s)
        """,
        item_parts,
    )

    image_rows = fetch_rows(
        legacy_conn,
        """
        SELECT id, item_part_id, iipimage, image, locus
        FROM digipal_image
        ORDER BY id
        """,
    )
    rows_imported["manuscripts_itemimage"] = insert_rows(
        target_conn,
        """
        INSERT INTO manuscripts_itemimage (id, item_part_id, image, locus)
        VALUES (%(id)s, %(item_part_id)s, %(image)s, %(locus)s)
        """,
        [
            {
                "id": row["id"],
                "item_part_id": row["item_part_id"] or -1,
                "image": truncate(legacy_image_path(row["iipimage"], row["image"]), 200),
                "locus": truncate(row["locus"] or "", 72),
            }
            for row in image_rows
        ],
    )
    return rows_imported


def import_scribes_hands(ctx: ImportContext) -> dict[str, int]:
    legacy_conn = ctx.legacy_conn
    target_conn = ctx.target_conn
    rows_imported: dict[str, int] = {}

    scribe_rows = fetch_rows(legacy_conn, "SELECT id, name FROM digipal_scribe ORDER BY id")
    scribes = [{"id": -1, "name": "[name] update records relations later", "scriptorium": "", "period_id": None}]
    scribes.extend(
        {"id": row["id"], "name": text_or_blank(row["name"]), "scriptorium": "", "period_id": None}
        for row in scribe_rows
    )
    rows_imported["scribes_scribe"] = insert_rows(
        target_conn,
        """
        INSERT INTO scribes_scribe (id, name, scriptorium, period_id)
        VALUES (%(id)s, %(name)s, %(scriptorium)s, %(period_id)s)
        """,
        scribes,
    )

    script_rows = fetch_rows(legacy_conn, "SELECT id, name FROM digipal_script ORDER BY id")
    rows_imported["scribes_script"] = insert_rows(
        target_conn,
        "INSERT INTO scribes_script (id, name) VALUES (%(id)s, %(name)s)",
        [{"id": row["id"], "name": text_or_blank(row["name"])} for row in script_rows],
    )

    hand_rows = fetch_rows(
        legacy_conn,
        """
        SELECT
          id,
          item_part_id,
          scribe_id,
          script_id,
          assigned_date_id,
          assigned_place_id,
          label,
          display_label,
          internal_note,
          display_note,
          comments,
          num
        FROM digipal_hand
        ORDER BY id
        """,
    )
    hands = []
    for row in hand_rows:
        description_parts = [
            str(value).strip()
            for value in (row["display_note"], row["internal_note"], row["comments"])
            if value is not None and str(value).strip()
        ]
        hands.append(
            {
                "id": row["id"],
                "scribe_id": row["scribe_id"] or -1,
                "item_part_id": row["item_part_id"],
                "script_id": row["script_id"],
                "name": truncate(row["label"] or row["display_label"] or f"Hand {row['id']}", 100),
                "num": row["num"] or 1,
                "priority": 0,
                "is_default": False,
                "date_id": row["assigned_date_id"],
                "place": "",
                "description": "\n\n".join(description_parts),
            }
        )
    rows_imported["scribes_hand"] = insert_rows(
        target_conn,
        """
        INSERT INTO scribes_hand (
          id, scribe_id, item_part_id, script_id, name, num, priority, is_default, date_id, place, description
        )
        VALUES (
          %(id)s, %(scribe_id)s, %(item_part_id)s, %(script_id)s, %(name)s, %(num)s, %(priority)s,
          %(is_default)s, %(date_id)s, %(place)s, %(description)s
        )
        """,
        hands,
    )

    hand_image_rows = fetch_rows(
        legacy_conn,
        """
        SELECT id, hand_id, image_id AS itemimage_id
        FROM digipal_hand_images
        ORDER BY id
        """,
    )
    rows_imported["scribes_hand_item_part_images"] = insert_rows(
        target_conn,
        """
        INSERT INTO scribes_hand_item_part_images (id, hand_id, itemimage_id)
        VALUES (%(id)s, %(hand_id)s, %(itemimage_id)s)
        """,
        hand_image_rows,
    )
    return rows_imported


def import_image_text(ctx: ImportContext) -> dict[str, int]:
    rows = fetch_rows(
        ctx.legacy_conn,
        """
        WITH image_choice AS (
          SELECT DISTINCT ON (item_part_id)
            item_part_id,
            id AS item_image_id
          FROM digipal_image
          WHERE item_part_id IS NOT NULL
          ORDER BY
            item_part_id,
            CASE
              WHEN lower(COALESCE(locus, '')) = 'face' THEN 0
              WHEN lower(COALESCE(locus, '')) LIKE 'face%%' THEN 1
              ELSE 2
            END,
            id
        )
        SELECT
          x.content,
          x.created,
          x.modified,
          t.slug AS type_slug,
          s.slug AS status_slug,
          '' AS language,
          ic.item_image_id
        FROM digipal_text_textcontentxml x
        JOIN digipal_text_textcontent c ON c.id = x.text_content_id
        JOIN digipal_text_textcontenttype t ON t.id = c.type_id
        JOIN digipal_text_textcontentxmlstatus s ON s.id = x.status_id
        JOIN image_choice ic ON ic.item_part_id = c.item_part_id
        WHERE x.content IS NOT NULL AND btrim(x.content) <> ''
        ORDER BY c.item_part_id, t.slug, x.id
        """,
    )
    values = []
    for row in rows:
        type_value = "Translation" if row["type_slug"] == "translation" else "Transcription"
        status_value = {
            "draft": "Draft",
            "review": "Review",
            "live": "Live",
            "reviewed": "Reviewed",
        }.get(row["status_slug"], "Draft")
        values.append(
            {
                "item_image_id": row["item_image_id"],
                "content": row["content"],
                "type": type_value,
                "status": status_value,
                "language": row["language"] or "",
                "created": row["created"],
                "modified": row["modified"],
            }
        )
    return {
        "manuscripts_imagetext": insert_rows(
            ctx.target_conn,
            """
            INSERT INTO manuscripts_imagetext (
              item_image_id, content, type, status, language, created, modified, content_dpt_legacy,
              review_assignee_id
            )
            VALUES (
              %(item_image_id)s, %(content)s, %(type)s, %(status)s, %(language)s, %(created)s, %(modified)s,
              NULL, NULL
            )
            """,
            values,
        )
    }


def import_annotations(ctx: ImportContext) -> dict[str, int]:
    legacy_conn = ctx.legacy_conn
    target_conn = ctx.target_conn
    rows_imported: dict[str, int] = {}

    annotation_rows = fetch_rows(
        legacy_conn,
        """
        SELECT
          a.id,
          a.image_id AS item_image_id,
          a.geo_json,
          a.display_note,
          a.internal_note,
          a.type,
          a.created,
          a.graph_id,
          g.hand_id,
          i.allograph_id
        FROM digipal_annotation a
        LEFT JOIN digipal_graph g ON g.id = a.graph_id
        LEFT JOIN digipal_idiograph i ON i.id = g.idiograph_id
        ORDER BY a.id
        """,
    )
    annotations = []
    missing_image_links = []
    for row in annotation_rows:
        annotation_type = row["type"] or ("image" if row["graph_id"] is not None else "unknown")
        allograph_id = row["allograph_id"] if annotation_type == "image" else None
        hand_id = row["hand_id"] if annotation_type == "image" else None
        if annotation_type == "image" and (allograph_id is None or hand_id is None):
            missing_image_links.append(row["id"])
        annotations.append(
            {
                "id": row["id"],
                "item_image_id": row["item_image_id"],
                "annotation": json.dumps(parse_annotation(row["geo_json"])),
                "note": text_or_blank(row["display_note"]),
                "internal_note": text_or_blank(row["internal_note"]),
                "allograph_id": allograph_id,
                "hand_id": hand_id,
                "annotation_type": annotation_type,
                "created": row["created"],
            }
        )
    if missing_image_links:
        sample = ", ".join(str(value) for value in missing_image_links[:10])
        raise LegacyMigrationImportError(f"Image annotations are missing hand/allograph links. Sample ids: {sample}")

    rows_imported["annotations_graph"] = insert_rows(
        target_conn,
        """
        INSERT INTO annotations_graph (
          id, item_image_id, annotation, note, internal_note, allograph_id, hand_id, annotation_type, created
        )
        VALUES (
          %(id)s, %(item_image_id)s, %(annotation)s::jsonb, %(note)s, %(internal_note)s, %(allograph_id)s,
          %(hand_id)s, %(annotation_type)s, %(created)s
        )
        """,
        annotations,
    )

    graph_component_rows = fetch_rows(
        legacy_conn,
        """
        SELECT DISTINCT ON (a.id, gc.component_id)
          gc.id,
          a.id AS graph_id,
          gc.component_id
        FROM digipal_graphcomponent gc
        JOIN digipal_annotation a ON a.graph_id = gc.graph_id
        ORDER BY a.id, gc.component_id, gc.id
        """,
    )
    rows_imported["annotations_graphcomponent"] = insert_rows(
        target_conn,
        """
        INSERT INTO annotations_graphcomponent (id, graph_id, component_id)
        VALUES (%(id)s, %(graph_id)s, %(component_id)s)
        """,
        graph_component_rows,
    )

    graph_component_feature_rows = fetch_rows(
        legacy_conn,
        """
        WITH mapped_gc AS (
          SELECT
            gc.id,
            min(gc.id) OVER (PARTITION BY a.id, gc.component_id) AS target_gc_id
          FROM digipal_graphcomponent gc
          JOIN digipal_annotation a ON a.graph_id = gc.graph_id
        )
        SELECT DISTINCT
          mg.target_gc_id AS graphcomponent_id,
          gcf.feature_id
        FROM digipal_graphcomponent_features gcf
        JOIN mapped_gc mg ON mg.id = gcf.graphcomponent_id
        ORDER BY mg.target_gc_id, gcf.feature_id
        """,
    )
    rows_imported["annotations_graphcomponent_features"] = insert_rows(
        target_conn,
        """
        INSERT INTO annotations_graphcomponent_features (graphcomponent_id, feature_id)
        VALUES (%(graphcomponent_id)s, %(feature_id)s)
        """,
        graph_component_feature_rows,
    )

    graph_position_rows = fetch_rows(
        legacy_conn,
        """
        SELECT DISTINCT
          a.id AS graph_id,
          ga.aspect_id AS position_id
        FROM digipal_graph_aspects ga
        JOIN digipal_annotation a ON a.graph_id = ga.graph_id
        ORDER BY a.id, ga.aspect_id
        """,
    )
    rows_imported["annotations_graph_positions"] = insert_rows(
        target_conn,
        """
        INSERT INTO annotations_graph_positions (graph_id, position_id)
        VALUES (%(graph_id)s, %(position_id)s)
        """,
        graph_position_rows,
    )
    return rows_imported


def import_publications(ctx: ImportContext) -> dict[str, int]:
    author_id = resolve_publication_author_id(
        ctx.target_conn,
        author_id=ctx.options.publication_author_id,
        username=ctx.options.publication_author_username,
    )
    legacy_conn = ctx.legacy_conn
    target_conn = ctx.target_conn
    rows_imported: dict[str, int] = {}

    category_rows = fetch_rows(
        legacy_conn,
        """
        SELECT
          c.id,
          c.title AS name,
          c.slug,
          count(bpc.id) AS count
        FROM blog_blogcategory c
        LEFT JOIN blog_blogpost_categories bpc ON bpc.blogcategory_id = c.id
        GROUP BY c.id, c.title, c.slug
        ORDER BY c.id
        """,
    )
    rows_imported["publications_tagulous_publication_keywords"] = insert_rows(
        target_conn,
        """
        INSERT INTO publications_tagulous_publication_keywords (id, name, slug, count, protected)
        VALUES (%(id)s, %(name)s, %(slug)s, %(count)s, false)
        """,
        [
            {
                "id": row["id"],
                "name": text_or_blank(row["name"]),
                "slug": text_or_blank(row["slug"]),
                "count": row["count"],
            }
            for row in category_rows
        ],
    )

    publication_rows = fetch_rows(
        legacy_conn,
        """
        SELECT
          b.id,
          b.title,
          b.slug,
          b.content,
          b.description,
          b.allow_comments,
          b.publish_date,
          b.created,
          b.updated,
          EXISTS (
            SELECT 1 FROM blog_blogpost_categories bc
            JOIN blog_blogcategory c ON c.id = bc.blogcategory_id
            WHERE bc.blogpost_id = b.id AND c.slug = 'blog'
          ) AS is_blog_post,
          EXISTS (
            SELECT 1 FROM blog_blogpost_categories bc
            JOIN blog_blogcategory c ON c.id = bc.blogcategory_id
            WHERE bc.blogpost_id = b.id AND c.slug = 'news'
          ) AS is_news,
          EXISTS (
            SELECT 1 FROM blog_blogpost_categories bc
            JOIN blog_blogcategory c ON c.id = bc.blogcategory_id
            WHERE bc.blogpost_id = b.id AND c.slug = 'feature-of-the-month'
          ) AS is_featured
        FROM blog_blogpost b
        ORDER BY b.id
        """,
    )
    rows_imported["publications_publication"] = insert_rows(
        target_conn,
        """
        INSERT INTO publications_publication (
          id, title, slug, content, preview, author_id, status, is_blog_post, is_news, is_featured,
          allow_comments, published_at, created_at, updated_at
        )
        VALUES (
          %(id)s, %(title)s, %(slug)s, %(content)s, %(preview)s, %(author_id)s, 'Published',
          %(is_blog_post)s, %(is_news)s, %(is_featured)s, %(allow_comments)s, %(published_at)s,
          %(created_at)s, %(updated_at)s
        )
        """,
        [
            {
                "id": row["id"],
                "title": truncate(row["title"] or f"Legacy publication {row['id']}", 350),
                "slug": truncate(row["slug"] or f"legacy-publication-{row['id']}", 150),
                "content": text_or_blank(row["content"]),
                "preview": text_or_blank(row["description"]),
                "author_id": author_id,
                "is_blog_post": row["is_blog_post"],
                "is_news": row["is_news"],
                "is_featured": row["is_featured"],
                "allow_comments": bool(row["allow_comments"]),
                "published_at": row["publish_date"],
                "created_at": row["created"] or row["publish_date"],
                "updated_at": row["updated"] or row["publish_date"],
            }
            for row in publication_rows
        ],
    )

    publication_keyword_rows = fetch_rows(
        legacy_conn,
        """
        SELECT id, blogpost_id AS publication_id, blogcategory_id AS tagulous_publication_keywords_id
        FROM blog_blogpost_categories
        ORDER BY id
        """,
    )
    rows_imported["publications_publication_keywords"] = insert_rows(
        target_conn,
        """
        INSERT INTO publications_publication_keywords (id, publication_id, tagulous_publication_keywords_id)
        VALUES (%(id)s, %(publication_id)s, %(tagulous_publication_keywords_id)s)
        """,
        publication_keyword_rows,
    )

    carousel_rows = fetch_rows(
        legacy_conn,
        """
        SELECT id, sort_order, image, image_file, title, link
        FROM digipal_carouselitem
        ORDER BY id
        """,
    )
    rows_imported["publications_carouselitem"] = insert_rows(
        target_conn,
        """
        INSERT INTO publications_carouselitem (id, ordering, image, title, url)
        VALUES (%(id)s, %(ordering)s, %(image)s, %(title)s, %(url)s)
        """,
        [
            {
                "id": row["id"],
                "ordering": row["sort_order"] or 0,
                "image": truncate(row["image_file"] or row["image"] or "", 100),
                "title": truncate(row["title"] or "", 150),
                "url": truncate(row["link"] or "", 200),
            }
            for row in carousel_rows
        ],
    )
    return rows_imported


def import_target_only(_ctx: ImportContext) -> dict[str, int]:
    return {}


PHASE_IMPORTERS = {
    "core_vocabularies": import_core_vocabularies,
    "symbols": import_symbols,
    "manuscripts": import_manuscripts,
    "scribes_hands": import_scribes_hands,
    "image_text": import_image_text,
    "annotations": import_annotations,
    "publications": import_publications,
    "target_only": import_target_only,
}


def import_report_to_dict(report: ImportReport) -> dict[str, Any]:
    return {
        "status": report.status,
        "dry_run": report.dry_run,
        "legacy_database": report.legacy_database,
        "target_database": report.target_database,
        "target_row_counts_before": report.target_row_counts_before,
        "target_row_counts_after": report.target_row_counts_after,
        "phases": [
            {
                "key": phase.key,
                "status": phase.status,
                "started_at": phase.started_at,
                "finished_at": phase.finished_at,
                "rows_planned": phase.rows_planned,
                "rows_imported": phase.rows_imported,
                "warnings": phase.warnings,
            }
            for phase in report.phases
        ],
        "audit": report.audit,
    }


def render_import_report_json(report: ImportReport) -> str:
    return json.dumps(import_report_to_dict(report), indent=2, sort_keys=True, default=str) + "\n"


def run_import(options: ImportOptions) -> ImportReport:
    phases = expand_phases(options.phases)
    legacy_url = options.legacy_url or legacy_url_from_env(base_url=options.target_url)
    target_url = options.target_url or target_url_from_env()

    try:
        legacy_conn = psycopg.connect(legacy_url)
        target_conn = psycopg.connect(target_url)
    except psycopg.Error as exc:
        raise LegacyMigrationImportError(f"Could not connect to legacy/target databases: {exc}") from exc

    configure_read_only_session(legacy_conn)
    target_conn.autocommit = True

    with legacy_conn, target_conn:
        legacy_db = database_name(legacy_conn)
        target_db = database_name(target_conn)
        if legacy_db == target_db:
            raise LegacyMigrationImportError("Legacy and target database URLs point at the same database.")

        try:
            require_tables(legacy_conn, REQUIRED_LEGACY_TABLES, database_label=f"legacy database {legacy_db}")
            require_tables(target_conn, REQUIRED_TARGET_TABLES, database_label=f"target database {target_db}")
        except LegacyMigrationAuditError as exc:
            raise LegacyMigrationImportError(str(exc)) from exc

        before_counts = target_domain_counts(target_conn)
        if options.execute:
            assert_target_ready(before_counts, phases, allow_non_empty_target=options.allow_non_empty_target)

        context = ImportContext(legacy_conn, target_conn, options)
        phase_results: list[PhaseResult] = []

        for phase in phases:
            started_at = utc_now_iso()
            planned = phase_plan_counts(legacy_conn, phase)
            imported: dict[str, int] = {}
            warnings: list[str] = []

            if phase == "target_only":
                warnings.append("No target-only data is imported from the legacy source database by design.")

            if options.execute and phase != "target_only":
                try:
                    with target_conn.transaction():
                        imported = PHASE_IMPORTERS[phase](context)
                        reset_sequences(target_conn, PHASE_TARGET_TABLES[phase])
                except Exception as exc:
                    phase_results.append(
                        PhaseResult(
                            key=phase,
                            status="fail",
                            started_at=started_at,
                            finished_at=utc_now_iso(),
                            rows_planned=planned,
                            rows_imported=imported,
                            warnings=[str(exc)],
                        )
                    )
                    raise LegacyMigrationImportError(f"Phase {phase} failed: {exc}") from exc

            phase_status = "warn" if warnings else "ok"
            phase_results.append(
                PhaseResult(
                    key=phase,
                    status=phase_status,
                    started_at=started_at,
                    finished_at=utc_now_iso(),
                    rows_planned=planned,
                    rows_imported=imported,
                    warnings=warnings,
                )
            )

        after_counts = target_domain_counts(target_conn)

    audit_dict = None
    if options.execute and not options.skip_post_audit:
        try:
            audit_report = run_audit(legacy_url=legacy_url, target_url=target_url)
        except LegacyMigrationAuditError as exc:
            raise LegacyMigrationImportError(f"Post-import audit failed to run: {exc}") from exc
        audit_dict = report_to_dict(audit_report)

    report = ImportReport(
        dry_run=not options.execute,
        legacy_database=legacy_db,
        target_database=target_db,
        phases=phase_results,
        target_row_counts_before=before_counts,
        target_row_counts_after=after_counts,
        audit=audit_dict,
    )
    if options.manifest_path:
        options.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        options.manifest_path.write_text(render_import_report_json(report), encoding="utf-8")

    if audit_dict and audit_dict["status"] == "fail":
        raise LegacyMigrationImportError("Post-import audit completed with status: fail")
    if audit_dict and audit_dict["status"] == "warn" and not options.allow_warnings:
        raise LegacyMigrationImportError(
            "Post-import audit completed with warnings. Re-run with --allow-warnings after recording them."
        )
    return report
