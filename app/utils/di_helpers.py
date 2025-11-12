"""Dependency injection helper utilities."""

from functools import lru_cache, wraps
from typing import TypeVar, Callable, Any

T = TypeVar('T')

def singleton(func: Callable[[], T]) -> Callable[[], T]:
    """
    Decorator to create singleton instances using lru_cache.
    Replaces repetitive @lru_cache(maxsize=1) patterns.
    """
    return lru_cache(maxsize=1)(func)

def compose(*funcs):
    """
    Compose multiple functions into a single function.
    Usage: composed = compose(f, g, h)  # equivalent to f(g(h(x)))
    """
    def composed_func(x):
        for func in reversed(funcs):
            x = func(x)
        return x
    return composed_func

def clear_singleton_cache(*funcs):
    """Clear cache for multiple singleton functions."""
    for func in funcs:
        if hasattr(func, 'cache_clear'):
            func.cache_clear()
