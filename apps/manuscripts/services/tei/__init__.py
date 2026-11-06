"""TEI conversion services.

`data_dpt_to_tei` and `tei_to_data_dpt` are mutual inverses between the TEI
in `ImageText.content` and the legacy `data-dpt` HTML the DigiPal import
left. The mapping they share lives in `mapping.py`. Round-trip fidelity across the live corpus is the
correctness bar (see tests).
"""

from .data_dpt_to_tei import data_dpt_to_tei
from .format import format_tei
from .links import (
    GraphRef,
    add_graph_ref,
    parse_graph_refs,
    referenced_graph_ids,
    remove_graph_ref,
    remove_graph_ref_at,
)
from .mapping import canonical_data_dpt
from .tei_to_data_dpt import contains_tei_element, tei_to_data_dpt
from .validate import validate_tei_wellformed

__all__ = [
    "canonical_data_dpt",
    "contains_tei_element",
    "data_dpt_to_tei",
    "format_tei",
    "tei_to_data_dpt",
    "validate_tei_wellformed",
    "GraphRef",
    "add_graph_ref",
    "parse_graph_refs",
    "referenced_graph_ids",
    "remove_graph_ref",
    "remove_graph_ref_at",
]
