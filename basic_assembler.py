from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, fields
from types import CodeType
from typing import Optional, Any, Iterable, Callable, Literal
import dis


def _strict_index(l, v):
    for i, e in enumerate(l):
        if v == e and type(v) == type(e):
            return i
    return l.index(v)


@dataclass
class Instruction:
    opcode: int
    arg: None | int | str | Label

    def __repr__(self):
        if self.opcode < dis.HAVE_ARGUMENT:
            return f"<{self.opname}>"

        else:
            return f"<{self.opname}: {self.arg!r}>"

    @property
    def opname(self):
        return dis.opname[self.opcode]

    @opname.setter
    def opname(self, value):
        self.opcode = dis.opmap[value]

    @property
    def is_jump(self):
        return self.opcode in dis.hasjrel or self.opcode in dis.hasjabs

    @property
    def no_next(self):
        return self.opname in ('RETURN_VALUE', 'JUMP_ABSOLUTE', 'JUMP_FORWARD')

    @classmethod
    def from_dis(cls, raw: dis.Instruction):
        return cls(raw.opcode, raw.argval)

    def get_raw(self, code_info: CodeInfo, o: int, j: Optional[int]) -> Iterable[dis.Instruction]:
        if self.opcode < dis.HAVE_ARGUMENT:
            yield dis.Instruction(self.opname, self.opcode, None, None, None, None, None, None)
            return
        if self.opcode in dis.hasname:
            arg_i = code_info.co_names.index(self.arg)
        elif self.opcode in dis.haslocal:
            arg_i = code_info.co_varnames.index(self.arg)
        elif self.opcode in dis.hasconst:
            arg_i = _strict_index(code_info.co_consts, self.arg)
        elif self.opcode in dis.hascompare:
            arg_i = dis.cmp_op.index(self.arg)
        elif self.opcode in dis.hasfree:
            arg_i = code_info.get_free_index(self.arg)
        elif self.opcode in dis.hasjrel and isinstance(self.arg, Label):
            arg_i = j - o - 1
        elif self.opcode in dis.hasjabs and isinstance(self.arg, Label):
            arg_i = j
        else:
            assert isinstance(self.arg, int), self.arg
            arg_i = self.arg
        assert arg_i >= 0
        vs = []
        while arg_i > 0xFF:
            vs.append(arg_i & 0xFF)
            arg_i >>= 8
        vs.append(arg_i)
        vs.reverse()
        for v in vs[:-1]:
            yield dis.Instruction('EXTENDED_ARG', dis.EXTENDED_ARG, v, None, None, None, None, None)
        yield dis.Instruction(self.opname, self.opcode, vs[-1], None, None, None, None, None)

    def stack_effect(self):
        if self.opcode < dis.HAVE_ARGUMENT:
            return dis.stack_effect(self.opcode, None)
        elif isinstance(self.arg, int):
            return dis.stack_effect(self.opcode, self.arg)
        else:
            return dis.stack_effect(self.opcode, 0)


def ins(opc: int | str, arg=None):
    if isinstance(opc, str):
        opc = dis.opmap[opc]
    if opc < dis.HAVE_ARGUMENT:
        assert arg is None
    return Instruction(opc, arg)


@dataclass
class CodeInfo:
    co_argcount: int
    co_posonlyargcount: int
    co_kwonlyargcount: int
    co_nlocals: int
    co_stacksize: int
    co_flags: int
    co_consts: list[Any, ...]
    co_names: list[str, ...]
    co_varnames: list[str, ...]
    co_filename: str
    co_name: str
    co_freevars: list[str, ...]
    co_cellvars: list[str, ...]

    @classmethod
    def from_code(cls, code: CodeType):
        args = {f.name:
                    list(v) if isinstance(v := getattr(code, f.name), tuple) else v
                for f in fields(cls)}
        return cls(**args)

    def get_free_index(self, name: str):
        if name in self.co_cellvars:
            return self.co_cellvars.index(name)
        else:
            return len(self.co_cellvars) + self.co_freevars.index(name)

    def build(self, **kwargs):
        args = {f.name:
                    tuple(v) if isinstance(v := getattr(self, f.name), list) else v
                for f in fields(self)}
        args.update(kwargs)
        return CodeType(
            args["co_argcount"],
            args["co_posonlyargcount"],
            args["co_kwonlyargcount"],
            args["co_nlocals"],
            args["co_stacksize"],
            args["co_flags"],
            args["co_code"],
            args["co_consts"],
            args["co_names"],
            args["co_varnames"],
            args["co_filename"],
            args["co_name"],
            args["co_firstlineno"],
            args["co_lnotab"],
            args["co_freevars"],
            args["co_cellvars"],
        )

    def make_sure(self, name: Literal['consts', 'names', 'varnames', 'freevars', 'cellvars'], value) -> int:
        l: list = getattr(self, "co_" + name)
        if value not in l:
            l.append(value)
        return l.index(value)


@dataclass(frozen=True)
class Label(ABC):
    pass


@dataclass(frozen=True)
class BasicBlockTarget(Label):
    target_id: int
    offset: int


@dataclass
class Block(ABC):
    code_info: CodeInfo
    id: int

    @abstractmethod
    def as_basic_blocks(self) -> list[BasicBlock]:
        raise NotImplementedError


@dataclass
class BasicBlock(Block):
    instructions: list[Instruction]
    jump_instruction: Optional[Instruction]
    next_target: Optional[Label]
    line: int = None

    def as_basic_blocks(self) -> list[BasicBlock]:
        return [self]


def _to_bytes(raw: list[dis.Instruction]) -> bytes:
    out = bytearray()
    for i in raw:
        out.append(i.opcode)
        out.append(i.arg or 0)
    return bytes(out)


def _to_linetab(offsets: dict[int, int], end: int) -> tuple[int, bytes]:
    out = bytearray()
    lo = 0
    startline = None
    ll = None
    lll = None
    for o, l in sorted(offsets.items()) + [(end, None)]:
        if startline is None:
            startline = l - 1
            ll = l
            lll = l - 1
            continue
        dl = ll - lll
        do = o - lo
        ddl = -1 if dl < 0 else 1
        dl = abs(dl)
        while dl > 127:
            out.extend((0, 127 * ddl))
            dl -= 127
        out.extend((min(255, do), dl * ddl % 256))
        do -= 255
        while do > 0:
            out.extend((min(255, do), 0))
            do -= 255
        lll, ll = ll, l
        lo = o
    return startline, bytes(out)


@dataclass
class FunctionBlock(Block):
    entry: int
    blocks: dict[int, Block]

    def as_basic_blocks(self) -> list[BasicBlock]:
        runs_by_start = {}
        runs_by_target = {}
        for b in self.blocks.values():
            bbs = b.as_basic_blocks()
            for bb in bbs:
                assert bb.id not in runs_by_start, f"Duplicate block ids {bb}"
                runs_by_start[bb.id] = [bb]
                if bb.next_target is not None:
                    assert isinstance(bb.next_target, BasicBlockTarget), bb.next_target
                    assert bb.next_target.offset == 0, bb.next_target
                    assert bb.next_target.target_id not in runs_by_target, f"Duplicate target id {bb}"
                    runs_by_target[bb.next_target.target_id] = runs_by_start[bb.id]
        while runs_by_target:
            target_id, start_run = runs_by_target.popitem()
            assert target_id in runs_by_start, "Can't find target block"
            runs_by_start.pop(start_run[0].id)
            end_run = runs_by_start.pop(target_id)
            run = start_run + end_run
            if run[-1].next_target is not None:
                assert isinstance(run[-1].next_target, BasicBlockTarget), run[-1].next_target
                assert runs_by_target[run[-1].next_target.target_id] is end_run
                runs_by_target[run[-1].next_target.target_id] = run
            runs_by_start[run[0].id] = run
        result = runs_by_start.pop(self.entry)
        while runs_by_start:
            result.extend(runs_by_start.pop(min(runs_by_start)))
        return result

    def get_instructions(self) -> tuple[dict[int, int], dict[int, int | None], list[Instruction]]:
        jumps = {}
        block_starts = {}
        line_starts = {}
        ins = []
        last_line = None
        to_fix = []
        for b in self.as_basic_blocks():
            block_starts[b.id] = len(ins)
            if b.line != last_line:
                line_starts[len(ins)] = b.line
                last_line = b.line
            ins.extend(b.instructions)
            if b.jump_instruction is not None:
                assert isinstance(b.jump_instruction.arg, BasicBlockTarget)
                to_fix.append(len(ins))
                ins.append(b.jump_instruction)
        for i in to_fix:
            l = ins[i].arg
            assert isinstance(l, BasicBlockTarget)
            jumps[i] = block_starts[l.target_id] + l.offset
        return jumps, line_starts, ins

    def assemble(self) -> CodeType:
        jumps, line_starts, ins = self.get_instructions()
        actual_targets = {o: o for o in jumps.values()}
        old_hash = None
        raw_ins = None
        line_offsets = None
        while old_hash != hash(frozenset(actual_targets.items())):
            old_hash = hash(frozenset(actual_targets.items()))
            raw_ins = []
            line_offsets = {}
            for j, i in enumerate(ins):
                if j in actual_targets:
                    actual_targets[j] = len(raw_ins)
                if j in line_starts:
                    line_offsets[len(raw_ins) * 2] = line_starts[j]
                o = jumps.get(j, None)
                o = actual_targets.get(o, None)
                raw_ins.extend(i.get_raw(self.code_info, j, o))
        assert raw_ins is not None
        startline, linetab = _to_linetab(line_offsets, len(raw_ins) * 2)
        return self.code_info.build(
            co_code=_to_bytes(raw_ins),
            co_firstlineno=startline,
            co_lnotab=linetab
        )


@dataclass
class MetaBlock(Block):
    blocks: dict[int, Block]


def disassemble(code: CodeType) -> FunctionBlock:
    code_info = CodeInfo.from_code(code)
    block_id = 1
    blocks = {}
    labels = {}
    current: BasicBlock | None = None
    last: BasicBlock | None = None
    line = None
    current_start: int | None = None
    to_fix = []
    for raw in dis.get_instructions(code):
        if raw.starts_line is not None:
            line = raw.starts_line
            if current is not None:
                assert last is None
                last, current = current, None
        if current is None:
            current = BasicBlock(code_info, block_id, [], None, None, line)
            if last is not None:
                assert last.next_target is None
                last.next_target = BasicBlockTarget(block_id, 0)
                last = None
            blocks[block_id] = current
            current_start = raw.offset
            block_id += 1
        if raw.is_jump_target:
            labels[raw.offset] = BasicBlockTarget(current.id, (raw.offset - current_start) // 2)
        ins = Instruction.from_dis(raw)
        if not ins.is_jump:
            current.instructions.append(ins)
        else:
            current.jump_instruction = ins
            to_fix.append(ins)
            last, current = current, None
        if ins.no_next:
            last = current = None
    for ins in to_fix:
        ins.arg = labels[ins.arg]
    return FunctionBlock(code_info, 0, 1, blocks)


def nop(func):
    b = disassemble(func.__code__)
    func.__code__ = b.assemble()
    return func
