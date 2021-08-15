from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from collections import ChainMap
from dataclasses import dataclass, field
from itertools import chain
from typing import Generic, TypeVar, Sequence, Iterable, Any, Callable, Optional, Collection

T = TypeVar('T')


def _capture(name: Any | None, value) -> dict:
    if name is None:
        return {}
    else:
        return {name: value}


@dataclass
class MatchResult(Generic[T]):
    start: int
    end: int
    orig: Sequence[T]
    captures: dict


class _NoMatch(BaseException):
    pass


@dataclass
class MatcherFirst:
    pattern: Pattern

    def fullmatch(self, stream: Sequence[T]) -> Optional[MatchResult]:
        captures = Captures()
        for i in self.pattern.match(stream, 0, captures):
            if i >= len(stream):
                return MatchResult(0, i, stream, captures.to_dict())
        else:
            return None

    def _match(self, stream: Sequence[T], start: int) -> MatchResult:
        captures = Captures()
        for i in self.pattern.match(stream, 0, captures):
            return MatchResult(0, i, stream, captures.to_dict())
        else:
            raise _NoMatch

    def match(self, stream: Sequence[T]) -> Optional[MatchResult]:
        try:
            return self._match(stream, 0)
        except _NoMatch:
            return None

    def search(self, stream: Sequence[T]) -> Optional[MatchResult]:
        start = 0
        while start < len(stream):
            try:
                return self._match(stream, start)
            except _NoMatch:
                start += 1

    def findall(self, stream: Sequence[T], overlapping: bool = False) -> Iterable[MatchResult]:
        start = 0
        while start < len(stream):
            try:
                r = self._match(stream, start)
                yield r
                start = r.end if not overlapping else start + 1
            except _NoMatch:
                start += 1


class MatcherLongest(MatcherFirst):
    def _match(self, stream: Sequence[T], start: int) -> MatchResult:
        best = None
        captures = Captures()
        for i in self.pattern.match(stream, 0, captures):
            r = MatchResult(0, i, stream, captures.to_dict())
            if best is None:
                best = r
            elif r.end > best.end:
                best = r
        if best is None:
            raise _NoMatch
        return best


@dataclass
class Captures:
    _internal: ChainMap = field(default_factory=ChainMap)
    _keys: list = field(default_factory=list)

    def enter(self):
        self._internal = self._internal.new_child()
        self._keys.append(key:=object())
        # print(">" * len(self._internal.maps),
        #       "Captures.enter called from",
        #       inspect.currentframe().f_back.f_locals["self"].__class__.__name__,
        #       "key", key)
        return key

    def exit(self, key):
        # print("<" * len(self._internal.maps),
        #       " Captures.exit called from",
        #       inspect.currentframe().f_back.f_locals["self"].__class__.__name__,
        #       "key", key)
        assert key is self._keys.pop()
        self._internal = self._internal.parents

    def maybe(self, name: Any | None, value):
        if name is not None:
            self[name] = value

    def __setitem__(self, key, value):
        self._internal[key] = value

    def __getitem__(self, item):
        return self._internal[item]

    def to_dict(self):
        return dict(self._internal)

    def extend(self, r: dict):
        self._internal.update(r)

@dataclass
class Back:
    name: Any

class Pattern(ABC, Generic[T]):
    @abstractmethod
    def match(self, stream: Sequence[T], start: int, captures: Captures) -> Iterable[int]:
        raise NotImplementedError

    def __or__(self, other):
        return Alternation([self, other])

    def __ror__(self, other):
        return Alternation([other, self])

    def __add__(self, other):
        return Concatenation([self, other])

    def __radd__(self, other):
        return Concatenation([other, self])

    def __getitem__(self, item: slice | int):
        if not isinstance(item, slice):
            item = slice(item, item)
        return Repeat(self, item.start or 0, item.stop, item.step or 1)


@dataclass
class Alternation(Pattern[T]):
    patterns: list[Pattern, ...]

    def match(self, stream: Sequence[T], start: int, captures: Captures) -> Iterable[int]:
        for p in self.patterns:
            k = captures.enter()
            yield from p.match(stream, start, captures)
            captures.exit(k)

    def __or__(self, other):
        if isinstance(other, Alternation):
            return Alternation([*self.patterns, *other.patterns])
        else:
            return Alternation([*self.patterns, other])

    def __ror__(self, other):
        if isinstance(other, Alternation):
            return Alternation([*other.patterns, *self.patterns])
        else:
            return Alternation([other, *self.patterns])


@dataclass
class Lookahead(Pattern[T]):
    base: Pattern[T]
    no_captures: bool = False

    def match(self, stream: Sequence[T], start: int, captures) -> Iterable[int]:
        k = captures.enter()
        for r in self.base.match(stream, start, captures):
            yield start
        captures.exit(k)


class EOS(Pattern[T]):
    def match(self, stream: Sequence[T], start: int, captures) -> Iterable[int]:
        if start >= len(stream):
            yield start


@dataclass
class Concatenation(Pattern[T]):
    patterns: list[Pattern, ...]

    def match(self, stream: Sequence[T], start: int, captures) -> Iterable[int]:
        keys_stack = [captures.enter()]
        iter_stack = [iter(self.patterns[0].match(stream, start, captures))]
        result_stack = []
        while iter_stack:
            assert len(iter_stack) == len(keys_stack)
            if len(result_stack) < len(iter_stack):
                try:
                    result_stack.append(next(iter_stack[len(result_stack)]))
                except StopIteration:
                    iter_stack.pop()
                    captures.exit(keys_stack.pop())
                    if not result_stack:
                        return
                    result_stack.pop()
            elif len(iter_stack) < len(self.patterns):
                keys_stack.append(captures.enter())
                iter_stack.append(iter(self.patterns[len(iter_stack)].match(stream, result_stack[-1], captures)))
            elif len(result_stack) == len(iter_stack) == len(self.patterns):
                i = result_stack[-1]
                yield i
                result_stack.pop()

    def __add__(self, other):
        if isinstance(other, Concatenation):
            return Concatenation([*self.patterns, *other.patterns])
        else:
            return Concatenation([*self.patterns, other])

    def __radd__(self, other):
        if isinstance(other, Concatenation):
            return Concatenation([*other.patterns, *self.patterns])
        else:
            return Concatenation([other, *self.patterns])


@dataclass
class Repeat(Pattern[T]):
    base: Pattern[T]
    min: int
    max: Optional[int]
    step: int = 1

    # longest_first: bool = False

    def match(self, stream: Sequence[T], start: int, captures) -> Iterable[int]:
        if self.min == 0:
            yield start, {}
        keys_stack = [captures.enter()]
        iter_stack = [self.base.match(stream, start, captures)]
        result_stack = []
        while iter_stack:
            assert len(iter_stack) == len(keys_stack)
            if len(result_stack) < len(iter_stack):
                try:
                    result_stack.append(next(iter_stack[len(result_stack)]))
                except StopIteration:
                    iter_stack.pop()
                    captures.exit(keys_stack.pop())
                    if not iter_stack:
                        return
                    result_stack.pop()
            elif len(iter_stack) < self.min:
                keys_stack.append(captures.enter())
                iter_stack.append(iter(self.base.match(stream, result_stack[-1], captures)))
            elif len(result_stack) == len(iter_stack):
                if (len(iter_stack) - self.min) % self.step == 0:
                    yield result_stack[-1]
                if self.max is None or len(iter_stack) < self.max:
                    keys_stack.append(captures.enter())
                    iter_stack.append(iter(self.base.match(stream, result_stack[-1], captures)))
                else:
                    result_stack.pop()


@dataclass
class Any(Pattern[T]):
    capture: Any | None = None
    length: int | Sequence[int] = 1

    def match(self, stream: Sequence[T], start: int, captures) -> Iterable[int]:
        if start >= len(stream):
            return
        if isinstance(self.length, int):
            if start + self.length > len(stream):
                return
            captures.maybe(self.capture, stream[start:start + self.length])
            yield start + self.length
        else:
            for l in self.length:
                if start + l > len(stream):
                    continue
                k = captures.enter()
                captures.maybe(self.capture, stream[start:start + l])
                yield start + l
                captures.exit(k)


@dataclass
class DirectMatch(Pattern[T]):
    value: T
    capture: Any | None = None

    def match(self, stream: Sequence[T], start: int, captures) -> Iterable[int]:
        if start >= len(stream):
            return
        if stream[start] == self.value:
            captures.maybe(self.capture, stream[start])
            yield start + 1


@dataclass
class FunctionMatch(Pattern[T]):
    func: Callable[[Captures, T], None | bool | dict]
    capture: Any | None = None

    def match(self, stream: Sequence[T], start: int, captures) -> Iterable[int]:
        if start >= len(stream):
            return
        r = self.func(captures, stream[start])
        if r is None or r is False or (not r and r != {}):
            return
        captures.maybe(self.capture, stream[start])
        if isinstance(r, dict):
            captures.extend(r)
        yield start + 1


@dataclass
class AnyOfMatch(Pattern[T]):
    options: Collection[T]
    capture: Any | None = None

    def match(self, stream: Sequence[T], start: int, captures) -> Iterable[int]:
        if start >= len(stream):
            return
        v = stream[start]
        if v in self.options:
            captures.maybe(self.capture, v)
            yield start + 1


@dataclass
class StringMatch(Pattern[str]):
    s: str

    def match(self, stream: Sequence[str] | str, start: int, captures) -> Iterable[int]:
        if isinstance(stream, str):
            if stream[start:start + len(self.s)] == self.s:
                yield start + len(self.s)
        else:
            if len(stream) >= start:
                return
            if stream[start] == self.s:
                yield start + 1
