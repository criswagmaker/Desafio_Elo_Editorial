import time
from functools import wraps
from typing import Any, Callable, Dict

def log_tool_call(tool_name: str):
    """Decorator simples para mensurar duração da chamada de tool e imprimir log."""
    def decorator(func: Callable[..., Any]):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                ok = True
                return result
            except Exception as e: # pragma: no cover
                ok = False
                raise
            finally:
                duration_ms = int((time.time() - start) * 1000)
                status = "OK" if ok else "ERROR"
                print(
                    f"[tool] name={tool_name} status={status} duration_ms={duration_ms}"
                )
        return wrapper
    return decorator