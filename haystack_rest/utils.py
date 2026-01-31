from copy import deepcopy
from typing import Any


def merge_dict(a: dict[str, Any], b: dict[str, Any] | Any) -> dict[str, Any] | Any:
    """Recursively merge b into a. List values are combined and sorted."""
    if not isinstance(b, dict):
        return b
    result = deepcopy(a)
    for key, val in b.items():
        if key in result and isinstance(result[key], dict):
            result[key] = merge_dict(result[key], val)
        elif key in result and isinstance(result[key], list):
            result[key] = sorted(set(val) | set(result[key]))
        else:
            result[key] = deepcopy(val)
    return result
