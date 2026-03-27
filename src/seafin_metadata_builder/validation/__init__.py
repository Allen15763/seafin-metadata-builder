"""
Metadata Builder - 驗證模組

提供資料驗證功能，如 Circuit Breaker。
"""

from .circuit_breaker import CircuitBreaker, CircuitBreakerResult

__all__ = [
    "CircuitBreaker",
    "CircuitBreakerResult",
]
