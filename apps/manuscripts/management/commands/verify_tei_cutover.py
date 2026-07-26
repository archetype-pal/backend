"""Phase H.11 pre-cutover gate — is it safe to drop `ImageText.content_dpt_legacy`?

Run this **against production** immediately before applying the drop migration
(`0024_remove_imagetext_content_dpt_legacy`). Dropping the column permanently
destroys the ability to roll the TEI migration back, so the decision is gated on
evidence, not on a calendar. Exits 0 only when every mechanical check passes.

Strictly read-only: it issues SELECTs and introspection queries, nothing else.

Exit codes:
- 0 — every mechanical check passed; the drop loses nothing (modulo any
  superseded rows explicitly accepted, which are spelled out in the report).
- 1 — at least one check failed. Do not apply the drop.
- 2 — the column is already absent, so there is nothing to gate. Deliberately
  non-zero: "already applied" must never be mistaken by a script (or a human
  reading only the exit status) for "verified safe to apply". The most likely
  operator error before an irreversible drop — pointing the command at the
  wrong `DATABASE_URL` — lands here or on the `corpus-size` failure.

The column is read with raw SQL on purpose. This command ships in the same
commit that removes the field from the model, so at the moment it matters — the
deployed code is post-H.11 but the database still has the column — the ORM
cannot see it. Raw SQL also lets the gate report sanely once the column is gone.

What it checks (roadmap H.11 checklist item 1's "no rollback executed" clause
and item 4, plus the load-bearing data questions the checklist leaves implicit):

- the corpus is at least `--min-rows` rows, so no check is vacuous;
- every `ImageText.content` is well-formed TEI;
- no `content` still holds `data-dpt` markup — that would mean the migration
  never completed, or a rollback was executed (checklist item 1, first clause);
- no row where the legacy column is the only surviving copy;
- the retained HTML is regenerable from the TEI (`tei_to_data_dpt(content)`
  reproduces it), which is the actual argument that the column carries no
  information the TEI cannot reproduce;
- rows whose retained HTML diverges *because an editor rewrote the TEI after the
  migration* are reported separately and block by default: for those rows the
  pre-edit HTML genuinely is unreproducible and the drop really does destroy it;
- the `tei_migration_failures` table is empty or absent (checklist item 4).

Checklist items 2 (search regression suite), 3 (no `data-dpt` support tickets),
5 (KNOWLEDGEBASE.md design principle #1) and item 1's re-index clause are human
judgements; the command prints them as an explicit hand-off rather than
pretending to decide them.
"""

from dataclasses import dataclass, field
from datetime import datetime, time

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.models import Max
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from apps.manuscripts.models import ImageText, StatusTransition
from apps.manuscripts.services.tei import canonical_data_dpt, tei_to_data_dpt, validate_tei_wellformed

LEGACY_COLUMN = "content_dpt_legacy"
FAILURES_TABLE = "tei_migration_failures"
_FETCH_SIZE = 500

# A status change writes `update_fields=["status", "review_assignee", "modified"]`
# and creates its `StatusTransition` in the same atomic block, so the two stamps
# land within microseconds. Anything inside this window is treated as "the last
# write was a status change", i.e. NOT evidence of a content edit.
_STATUS_WRITE_TOLERANCE_SECONDS = 5

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_NOTHING_TO_GATE = 2

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"
REVIEW = "REVIEW"

MANUAL_CHECKLIST = (
    "search re-index completed after the TEI migration (roadmap item 1, second clause)",
    "search regression suite returns the hit set captured at H.4 time",
    "no support tickets or editor reports referencing data-dpt",
    "KNOWLEDGEBASE.md design principle #1 updated to reflect TEI as canonical",
)


@dataclass
class Check:
    """One gate line: a name, a verdict, and the evidence behind it."""

    name: str
    status: str
    summary: str
    details: list[str] = field(default_factory=list)


@dataclass
class Scan:
    """Raw tallies from the single read-only pass over the corpus."""

    rows: int = 0
    with_legacy: int = 0
    regenerated: int = 0
    malformed: list[str] = field(default_factory=list)
    residue: list[int] = field(default_factory=list)
    sole_copy: list[int] = field(default_factory=list)
    not_regenerable: list[int] = field(default_factory=list)
    superseded: list[int] = field(default_factory=list)


class Command(BaseCommand):
    help = "Gate the H.11 cutover: verify dropping ImageText.content_dpt_legacy loses nothing. Read-only."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--report-limit",
            type=int,
            default=20,
            help="Maximum offending ids printed per check (default 20, minimum 1).",
        )
        parser.add_argument(
            "--min-rows",
            type=int,
            default=1,
            help=(
                "Fail unless the corpus has at least N image-text rows (default 1). "
                "State the size you expect (e.g. --min-rows 899) so a wrong DATABASE_URL "
                "cannot certify a cutover against the wrong database."
            ),
        )
        parser.add_argument(
            "--migrated-at",
            default=None,
            help=(
                "When the TEI migration ran (ISO date or datetime). A row whose content an editor "
                "rewrote after this is reported as superseded instead of as a plain regeneration "
                "failure — its retained HTML is stale by design. Superseded rows still block "
                "unless --accept-superseded is passed."
            ),
        )
        parser.add_argument(
            "--accept-superseded",
            action="store_true",
            help=(
                "Acknowledge that the pre-edit HTML retained for superseded rows is NOT "
                "reproducible from the current TEI and will be destroyed by the drop. Pass this "
                "only after reviewing every id the gate lists under legacy-superseded."
            ),
        )

    def handle(self, *args, **options) -> None:
        report_limit: int = options["report_limit"]
        if report_limit < 1:
            raise CommandError("--report-limit must be at least 1.")
        min_rows: int = options["min_rows"]
        if min_rows < 1:
            raise CommandError("--min-rows must be at least 1: a zero-row corpus can never justify the drop.")
        migrated_at = self._parse_migrated_at(options.get("migrated_at"))
        accept_superseded: bool = options["accept_superseded"]

        has_legacy = self._has_legacy_column()
        scan = self._scan(has_legacy=has_legacy, migrated_at=migrated_at)
        checks = self._checks_for(
            scan,
            has_legacy=has_legacy,
            min_rows=min_rows,
            accept_superseded=accept_superseded,
        )

        self._report(checks, scan, has_legacy=has_legacy, report_limit=report_limit)

        failed = [check for check in checks if check.status == FAIL]
        if failed:
            self.stderr.write(
                self.style.ERROR(
                    f"FAILED: {len(failed)} of {len(checks)} check(s) did not pass. Do NOT apply the drop migration."
                )
            )
            raise SystemExit(EXIT_FAILED)
        if not has_legacy:
            self.stderr.write(
                self.style.WARNING(
                    f"NOT A VERIFICATION: {LEGACY_COLUMN} is already absent, so nothing was gated. "
                    "If you expected the column, check DATABASE_URL / search_path."
                )
            )
            raise SystemExit(EXIT_NOTHING_TO_GATE)

    # --- checks -----------------------------------------------------------

    def _scan(self, *, has_legacy: bool, migrated_at: datetime | None) -> Scan:
        """Single pass over the corpus, accumulating every row-level tally."""
        scan = Scan()
        edited_since = self._ids_content_edited_after(migrated_at)

        for row_id, content, legacy in self._iter_rows(has_legacy=has_legacy):
            scan.rows += 1

            errors = validate_tei_wellformed(content)
            if errors:
                scan.malformed.append(f"ImageText #{row_id}: {errors[0]['message']}")
            if "data-dpt" in content:
                scan.residue.append(row_id)

            if not (legacy or "").strip():
                continue
            scan.with_legacy += 1

            if not content.strip():
                # The legacy column is the only surviving copy — dropping it
                # would lose the text outright.
                scan.sole_copy.append(row_id)
                continue
            if errors:
                # Regeneration from markup that doesn't parse tells us nothing;
                # the row already fails the well-formedness check above.
                continue

            if canonical_data_dpt(tei_to_data_dpt(content)) == canonical_data_dpt(legacy or ""):
                scan.regenerated += 1
            elif row_id in edited_since:
                scan.superseded.append(row_id)
            else:
                scan.not_regenerable.append(row_id)

        return scan

    def _checks_for(self, scan: Scan, *, has_legacy: bool, min_rows: int, accept_superseded: bool) -> list[Check]:
        checks = [
            self._check_corpus_size(scan, min_rows),
            self._verdict(
                "tei-wellformed",
                scan.malformed,
                ok=f"all {scan.rows} row(s) parse as well-formed TEI",
                bad="row(s) are not well-formed TEI XML",
            ),
            self._verdict(
                "no-data-dpt-residue",
                [f"ImageText #{row_id}" for row_id in scan.residue],
                ok="no row still holds data-dpt markup — no rollback was executed (roadmap item 1, first clause)",
                bad="row(s) still hold data-dpt markup — migration incomplete or rolled back",
            ),
        ]

        if not has_legacy:
            checks.append(
                Check(
                    "legacy-column",
                    SKIP,
                    f"{LEGACY_COLUMN} is already gone from {ImageText._meta.db_table} — nothing left to gate",
                )
            )
            checks.append(self._check_failures_table())
            return checks

        checks.append(
            self._verdict(
                "legacy-not-sole-copy",
                [f"ImageText #{row_id}" for row_id in scan.sole_copy],
                ok=f"no row where {LEGACY_COLUMN} is the only surviving copy",
                bad=f"row(s) have empty content and a populated {LEGACY_COLUMN} — dropping loses the text",
            )
        )
        checks.append(self._check_regenerable(scan))
        checks.append(self._check_superseded(scan, accept_superseded=accept_superseded))
        checks.append(self._check_failures_table())
        return checks

    def _check_corpus_size(self, scan: Scan, min_rows: int) -> Check:
        """Refuse to certify a cutover against a corpus that cannot support the claim.

        Zero rows (or fewer than expected) almost always means the wrong
        database, a replica mid-restore, or a schema the connection cannot see —
        exactly the state in which every other check passes vacuously.
        """
        if scan.rows < min_rows:
            return Check(
                "corpus-size",
                FAIL,
                f"{scan.rows} image-text row(s), expected at least {min_rows} — refusing to certify a "
                "cutover against an empty or unexpected corpus; check DATABASE_URL / search_path",
            )
        return Check("corpus-size", PASS, f"{scan.rows} image-text row(s) (at least {min_rows} expected)")

    def _check_regenerable(self, scan: Scan) -> Check:
        """The load-bearing check: the TEI can reproduce every retained value."""
        if scan.not_regenerable:
            offenders = [f"ImageText #{row_id}" for row_id in scan.not_regenerable]
            return Check(
                "legacy-regenerable",
                FAIL,
                f"{len(offenders)} retained value(s) do NOT regenerate from the TEI — dropping loses those bytes",
                offenders,
            )
        if scan.with_legacy and not scan.regenerated:
            # Everything was excused (superseded, malformed, sole-copy), so this
            # check verified nothing at all. Saying PASS here would be the exact
            # false green light the gate exists to prevent — most likely from a
            # --migrated-at earlier than the migration itself.
            return Check(
                "legacy-regenerable",
                FAIL,
                f"0 of {scan.with_legacy} retained value(s) were actually verified — this check proves "
                "nothing; re-check --migrated-at (is it the END of the migration window?) and the "
                "failures listed above",
            )
        return Check(
            "legacy-regenerable",
            PASS,
            f"{scan.regenerated} of {scan.with_legacy} retained value(s) regenerate from the TEI",
        )

    def _check_superseded(self, scan: Scan, *, accept_superseded: bool) -> Check:
        """Rows whose retained HTML is stale because the TEI was edited since.

        These are NOT harmless. The retained bytes are a pre-edit copy that the
        current TEI cannot reproduce, so the drop destroys them for real. That is
        usually fine (the pre-edit text is superseded), but it is a judgement,
        so it blocks until a human says otherwise.
        """
        if not scan.superseded:
            return Check("legacy-superseded", PASS, "no retained value was superseded by a post-migration edit")
        offenders = [f"ImageText #{row_id}" for row_id in scan.superseded]
        detail = (
            f"{len(offenders)} retained value(s) diverge because the TEI was edited after --migrated-at — "
            "their pre-edit HTML is NOT reproducible from the current TEI and WILL be destroyed by the drop"
        )
        if accept_superseded:
            return Check("legacy-superseded", REVIEW, f"{detail} (accepted via --accept-superseded)", offenders)
        return Check(
            "legacy-superseded",
            FAIL,
            f"{detail}; review each id and re-run with --accept-superseded if losing it is acceptable",
            offenders,
        )

    def _check_failures_table(self) -> Check:
        """Checklist item 4.

        Absent is *not* affirmative evidence: nothing in this codebase ever
        created or wrote this table — `migrate_imagetext_to_tei` only prints
        failed ids to stdout — so its absence proves nothing and is reported as
        SKIP. The real signal that no row failed the migration is
        `no-data-dpt-residue`: a failed row is left as data-dpt.
        """
        if FAILURES_TABLE not in connection.introspection.table_names():
            return Check(
                FAILURES_TABLE,
                SKIP,
                "table absent — the H.3 migration only ever reported failures to stdout, so this check "
                "carries no evidence; rely on no-data-dpt-residue above",
            )
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM {FAILURES_TABLE}")  # table name is a module constant
            count = cursor.fetchone()[0]
        if count:
            return Check(FAILURES_TABLE, FAIL, f"{count} unreviewed migration failure(s) recorded")
        return Check(FAILURES_TABLE, PASS, "table present and empty")

    def _verdict(self, name: str, offenders: list[str], *, ok: str, bad: str) -> Check:
        if offenders:
            return Check(name, FAIL, f"{len(offenders)} {bad}", offenders)
        return Check(name, PASS, ok)

    # --- data access (read-only) ------------------------------------------

    def _has_legacy_column(self) -> bool:
        with connection.cursor() as cursor:
            columns = connection.introspection.get_table_description(cursor, ImageText._meta.db_table)
        return any(column.name == LEGACY_COLUMN for column in columns)

    def _iter_rows(self, *, has_legacy: bool):
        """Stream (id, content, legacy) — raw SQL because the model no longer declares the column."""
        table = ImageText._meta.db_table
        columns = ["id", "content"] + ([LEGACY_COLUMN] if has_legacy else [])
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY id")  # identifiers are constants
            while True:
                chunk = cursor.fetchmany(_FETCH_SIZE)
                if not chunk:
                    return
                for row in chunk:
                    yield row[0], row[1] or "", (row[2] if has_legacy else None)

    def _ids_content_edited_after(self, migrated_at: datetime | None) -> set[int]:
        """Rows whose *content* an editor plausibly rewrote after the migration.

        `modified` alone is not proof of a content edit: the routine
        Draft→Review→Live workflow saves `update_fields=["status",
        "review_assignee", "modified"]` without touching `content`, so a status
        change would otherwise excuse a genuinely lossy row. Every such change
        also writes a `StatusTransition`, so a row whose latest transition
        coincides with `modified` had a status change as its last write and is
        NOT exempted. That errs towards failing the gate, which is the correct
        direction for an irreversible operation.
        """
        if migrated_at is None:
            return set()
        candidates = dict(ImageText.objects.filter(modified__gt=migrated_at).values_list("id", "modified"))
        if not candidates:
            return set()
        latest_transitions = (
            StatusTransition.objects.filter(image_text_id__in=list(candidates))
            .values("image_text_id")
            .annotate(last=Max("created"))
        )
        explained: set[int] = set()
        for row in latest_transitions:
            gap = abs((candidates[row["image_text_id"]] - row["last"]).total_seconds())
            if gap <= _STATUS_WRITE_TOLERANCE_SECONDS:
                explained.add(row["image_text_id"])
        return set(candidates) - explained

    def _parse_migrated_at(self, raw: str | None) -> datetime | None:
        if not raw:
            return None
        value = parse_datetime(raw)
        if value is None:
            as_date = parse_date(raw)
            value = datetime.combine(as_date, time.min) if as_date else None
        if value is None:
            raise CommandError(f"--migrated-at is not an ISO date or datetime: {raw!r}")
        if timezone.is_naive(value):
            value = timezone.make_aware(value)
        return value

    # --- reporting --------------------------------------------------------

    def _report(self, checks: list[Check], scan: Scan, *, has_legacy: bool, report_limit: int) -> None:
        self.stdout.write(f"--- TEI cutover gate (H.11: drop {ImageText._meta.db_table}.{LEGACY_COLUMN}) ---")
        self.stdout.write(f"image-text rows: {scan.rows}")
        self.stdout.write(f"rows with retained legacy html: {scan.with_legacy if has_legacy else 'n/a'}")
        self.stdout.write("")

        styles = {
            PASS: self.style.SUCCESS,
            FAIL: self.style.ERROR,
            SKIP: self.style.WARNING,
            REVIEW: self.style.WARNING,
        }
        for check in checks:
            self.stdout.write(styles[check.status](f"[{check.status}] {check.name} — {check.summary}"))
            for line in check.details[:report_limit]:
                self.stdout.write(f"    {line}")
            if check.details and len(check.details) > report_limit:
                self.stdout.write(f"    ... and {len(check.details) - report_limit} more")

        self.stdout.write("")
        if any(check.status == FAIL for check in checks):
            return
        if not has_legacy:
            self.stdout.write(
                self.style.WARNING(
                    f"Nothing to gate: {LEGACY_COLUMN} is already absent from this database. "
                    "That is not a verification — no claim is made about whether the drop was safe."
                )
            )
            return
        if scan.superseded:
            self.stdout.write(
                self.style.WARNING(
                    f"Mechanical checks passed, with {len(scan.superseded)} accepted superseded row(s): "
                    "their retained pre-edit HTML cannot be regenerated from the current TEI and is "
                    "destroyed by the drop. Every other retained value is reproducible from the TEI."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "All mechanical checks passed: dropping the column loses no information the TEI cannot reproduce."
                )
            )
        self.stdout.write("Still a human call before applying the drop migration:")
        for item in MANUAL_CHECKLIST:
            self.stdout.write(f"  - {item}")
