"""
Path matching utilities for excluding paths from middleware processing.

This module provides functions to check if a request path should be excluded
from observability middleware based on configured patterns.
"""
import fnmatch
from typing import Optional, List, Dict, Union


def should_exclude_path(
    path: str,
    method: str,
    excluded_paths: Optional[Union[List[str], Dict[str, List[str]]]]
) -> bool:
    """
    Check if a request path should be excluded from middleware processing.

    Args:
        path: The request path (e.g., '/api/health', '/stream/events')
        method: The HTTP method (e.g., 'GET', 'POST')
        excluded_paths: Configuration for excluded paths, can be:
            - None: No paths excluded
            - List[str]: List of path patterns to exclude for all methods
            - Dict[str, List[str]]: Method-specific path patterns

    Returns:
        True if the path should be excluded, False otherwise

    Examples:
        >>> # Exclude all methods
        >>> should_exclude_path('/health', 'GET', ['/health', '/metrics'])
        True

        >>> # Method-specific exclusion
        >>> should_exclude_path('/stream', 'GET', {'GET': ['/stream*']})
        True

        >>> # Wildcard patterns
        >>> should_exclude_path('/api/v1/stream/events', 'POST', ['/api/*/stream/*'])
        True
    """
    if excluded_paths is None:
        return False

    # Normalize path (remove query params if present)
    if '?' in path:
        path = path.split('?')[0]

    # Handle list format - applies to all methods
    if isinstance(excluded_paths, list):
        return _match_path_patterns(path, excluded_paths)

    # Handle dict format - method-specific patterns
    if isinstance(excluded_paths, dict):
        # Check method-specific patterns
        method_patterns = excluded_paths.get(method.upper(), [])
        if _match_path_patterns(path, method_patterns):
            return True

        # Check wildcard method patterns (applies to all methods)
        all_patterns = excluded_paths.get('*', [])
        if _match_path_patterns(path, all_patterns):
            return True

    return False


def _match_path_patterns(path: str, patterns: List[str]) -> bool:
    """
    Check if a path matches any of the given patterns.

    Args:
        path: The request path to check
        patterns: List of patterns to match against

    Returns:
        True if the path matches any pattern, False otherwise
    """
    for pattern in patterns:
        # Handle exact matches
        if pattern == path:
            return True

        # Handle wildcard patterns using fnmatch
        if '*' in pattern or '?' in pattern:
            if fnmatch.fnmatch(path, pattern):
                return True

        # Handle path prefix matching (e.g., '/api/' matches '/api/anything')
        if pattern.endswith('/') and path.startswith(pattern):
            return True

    return False