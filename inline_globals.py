from __future__ import annotations

import dis
import inspect
from types import FunctionType
from typing import Iterable

from basic_assembler import disassemble, BasicBlock, find_pattern, FixedOpcode


def _get(func, name):
    if name in func.__globals__:
        return func.__globals__[name]
    else:
        return __builtins__[name]


def inline_globals(func_or_none=None, /, *, include: Iterable[str] = None, exclude: Iterable[str] = None):
    def wrapper(func: FunctionType):
        def to_const(bl: BasicBlock, i: int, _):
            ins = bl.instructions[i]
            if ins.arg not in names:
                return 
            try:
                ins.arg = _get(func, ins.arg)
                ins.opname = 'LOAD_CONST'
                code.code_info.make_sure('consts', ins.arg)
            except KeyError:
                return

        code = disassemble(func.__code__)
        names = set(include or code.code_info.co_names)
        names -= set(exclude or ())
        find_pattern(code, FixedOpcode(dis.opmap['LOAD_GLOBAL']), to_const)
        func.__orig_code__ = func.__code__
        func.__code__ = code.assemble()
        return func

    if func_or_none is None:
        return wrapper
    else:
        return wrapper(func_or_none)
