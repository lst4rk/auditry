"""Exception→response mapping resolution shared by the framework middlewares."""

from typing import List, Optional

from ..models import ExceptionMapping


def resolve_exception_mapping(
    error: BaseException,
    mappings: Optional[List[ExceptionMapping]],
) -> Optional[ExceptionMapping]:
    """
    Return the first configured mapping matching the error, or None.

    Single-leaf exception groups (anyio task groups wrap the real exception
    this way) are unwrapped before matching; detection is duck-typed on the
    `.exceptions` attribute so it works on Python < 3.11.
    """
    if not mappings:
        return None

    for _ in range(10):  # bounded unwrap of nested single-leaf groups
        subexceptions = getattr(error, "exceptions", None)
        if not (isinstance(subexceptions, (list, tuple)) and len(subexceptions) == 1):
            break
        error = subexceptions[0]

    for mapping in mappings:
        if isinstance(error, mapping.exception_type):
            return mapping
    return None
