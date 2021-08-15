from __future__ import annotations

from tail_call_optimization import tail_call_internal, tail_call


@tail_call_internal
def factorial(n, r=1):
    if n == 1:
        return r
    return factorial(n - 1, r * n)


@tail_call
def odd(n):
    if n == 0:
        return False
    else:
        return even(n - 1)


@tail_call
def even(n):
    if n == 0:
        return True
    return odd(n - 1)

