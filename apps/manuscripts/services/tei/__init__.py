"""TEI conversion services (Phase H).

`data_dpt_to_tei` and `tei_to_data_dpt` are mutual inverses over the
`data-dpt` HTML currently stored in `ImageText.content`. The mapping they
share lives in `mapping.py`. Round-trip fidelity across the live corpus is the
correctness bar (see tests).
"""

from .data_dpt_to_tei import data_dpt_to_tei
from .tei_to_data_dpt import tei_to_data_dpt

__all__ = ["data_dpt_to_tei", "tei_to_data_dpt"]
