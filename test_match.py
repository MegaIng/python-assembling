from __future__ import annotations

import dis
from dataclasses import dataclass
from typing import Any, Callable

from basic_assembler import disassemble, ins
from tail_call_optimization import tail_call_internal


@dataclass
class Thunk:
    func: Callable
    args: tuple[Any, ...]
    kwargs: dict[Any, ...]


@tail_call_internal
def force(k):
    match k:
        case Thunk(f, a, k):
            return force(f(*a, **k))
        case _:
            return k

def factorial(n, r=1):
    if n <= 1:
        return r
    return Thunk(factorial, (n-1, r*n), {})

dis.dis(force)

c = disassemble(force.__code__)
c.blocks[max(c.blocks)-1].instructions[0] = ins("PRINT_EXPR")
print(c.blocks[max(c.blocks)].instructions)
force.__code__ = c.assemble()

(force(factorial(10000)))
