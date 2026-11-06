from apps.search.exports import csv_fieldnames, to_bibtex
from apps.search.types import IndexType


def test_csv_fieldnames_is_the_union_in_first_seen_order_without_highlights():
    rows = [{"id": 1, "_formatted": {"id": "1"}, "name": "a"}, {"id": 2, "extra": "x"}, "not a dict"]
    assert csv_fieldnames(rows) == ["id", "name", "extra"]


def test_bibtex_keys_have_no_spaces_or_slashes():
    rows = [{"name": "Scribe A/B", "period": "c. 1150", "scriptorium": None}]
    entry = to_bibtex(rows, IndexType.SCRIBES)
    assert entry.startswith("@misc{scribe_Scribe_A_B_c._1150,")
    assert "  author = {Scribe A/B}," in entry and "  note = {Scriptorium: unknown}," in entry


def test_bibtex_per_index_shapes():
    hand_row = {"name": "Hand 1", "repository_name": "BL", "shelfmark": "MS 1", "place": "York", "date": "1100"}
    hand = to_bibtex([hand_row], IndexType.HANDS)
    assert hand.startswith("@misc{hand_BL_Hand_1_1100,") and "Place: York" in hand
    part_row = {"repository_name": "Durham", "display_label": "DCL A.II.4", "date_min": 1100}
    part = to_bibtex([part_row], IndexType.ITEM_PARTS)
    assert part.startswith("@misc{Durham_DCL_A.II.4_1100,") and "title = {DCL A.II.4}" in part
    assert to_bibtex(["not a dict"]) == ""
