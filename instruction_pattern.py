from __future__ import annotations

import dis
from _opcode import stack_effect
from abc import abstractmethod, ABC
from dataclasses import dataclass
from typing import Optional, Callable, Any, Sequence, Iterable, Collection

from basic_assembler import Block, FunctionBlock, BasicBlock, Instruction
from general_searching import Pattern, FunctionMatch, MatcherLongest, MatchResult, Back


class Missing:
    def __repr__(self):
        return "missing"


missing = Missing()


def fixed_opcode(opcode: int | str, fixed_arg: Any = missing, capture_arg: Any = missing) -> Pattern[Instruction]:
    if isinstance(opcode, str):
        opcode = dis.opmap[opcode]

    def match_opcode(captures, ins: Instruction):
        if ins.opcode != opcode:
            return False
        elif fixed_arg is not missing:
            if isinstance(fixed_arg, Back):
                if captures[fixed_arg.name] != ins.arg:
                    return False
            elif ins.arg != fixed_arg:
                return False

        if capture_arg is not missing:
            return {capture_arg: ins.arg}
        else:
            return True

    return FunctionMatch(match_opcode)


@dataclass
class StackEffectMatcher(Pattern[Instruction]):
    target: Collection[int] | Callable[[int], bool]
    capture_count: Any | None = None

    def match(self, stream: Sequence[Instruction], start: int, captures) -> Iterable[tuple[int, dict[Any]]]:
        stack = 0
        for i in range(start, len(stream)):
            stack += stream[i].stack_effect()
            if (not callable(self.target) and stack in self.target) or (callable(self.target) and self.target(stack)):
                k = captures.enter()
                captures.maybe(self.capture_count, stack)
                yield i + 1
                captures.exit(k)

# @dataclass
# class CallDescription

# @dataclass
# class CallMatcher(Pattern[Instruction]):
#     """Expects that some callable has been loaded to TOS before this activates (e.g. by LOAD_GLOBAL)"""
#     capture: Any | None = None
#     
#     def match(self, stream: Sequence[Instruction], start: int, captures) -> Iterable[tuple[int, dict[Any]]]:
#         



def find_pattern(block: Block, pattern: Pattern[Instruction], callback: Callable[[BasicBlock, MatchResult[Instruction]], None | bool]):
    """callbacks returns True when we should stop searching"""

    matcher = MatcherLongest(pattern)

    def recurse(bl: Block) -> bool:
        if isinstance(bl, FunctionBlock):
            for b in bl.blocks.values():
                if recurse(b):
                    return True
        elif isinstance(bl, BasicBlock):
            for r in matcher.findall(bl.instructions):
                if callback(bl, r):
                    return True
        else:
            raise NotImplementedError(bl)

    recurse(block)
