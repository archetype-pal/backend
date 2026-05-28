"""HTR import — PAGE-XML / ALTO → TEI (text_annotation plan, Phase 5).

The parsers return a list of `HtrLine` (text + optional polygon). `lines_to_tei`
builds a TEI body where each line is a `<seg type="line">` separated by `<lb/>`,
optionally carrying a `corresp` to a materialised region Graph. Emitting TEI
directly (no intermediate data-dpt) matches the post-pivot canonical storage.
"""

from .alto import alto_to_lines
from .builder import HtrLine, lines_to_tei
from .page_xml import page_xml_to_lines

__all__ = ["HtrLine", "lines_to_tei", "alto_to_lines", "page_xml_to_lines"]
