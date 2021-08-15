from __future__ import annotations

import dis
from dataclasses import dataclass
from functools import wraps
from hashlib import md5
from inspect import signature
from types import FunctionType
from typing import Callable, NamedTuple

from basic_assembler import disassemble, Instruction, BasicBlock, ins, BasicBlockTarget
from general_searching import Back, MatchResult
from instruction_pattern import find_pattern, fixed_opcode, StackEffectMatcher


@dataclass
class _OnStack:
    index: int


def tail_call_internal(func_or_none=None, /):
    def wrapper(func: FunctionType):
        def to_internal(bb: BasicBlock, r: MatchResult[Instruction]):
            assert bb.instructions[r.start].opname == "LOAD_GLOBAL" and bb.instructions[r.start].arg == func.__name__
            assert bb.instructions[r.end - 2].opname == "CALL_FUNCTION"
            assert bb.instructions[r.end - 1].opname == "RETURN_VALUE"
            assert r.end == len(bb.instructions)
            before = bb.instructions[:r.start]
            args = bb.instructions[r.start + 1:r.end - 2]
            argc = r.captures["argc"]
            bound = sig.bind(*map(_OnStack, range(argc)))
            bound.apply_defaults()
            bb.instructions = before + args
            to_store = []
            for name, value in bound.arguments.items():
                if isinstance(value, _OnStack):
                    to_store.append((name, value))
                else:
                    bb.code_info.make_sure("consts", value)
                    bb.instructions.append(ins("LOAD_CONSTANT", value))  # might be mutable. I don't care right now
                    bb.instructions.append(ins("STORE_FAST", name))
            to_store.sort(key=lambda t: t[1].index, reverse=True)
            current = argc - 1
            for name, i in to_store:
                assert i.index == current
                bb.instructions.append(ins("STORE_FAST", name))
                current -= 1
            bb.instructions.append(ins("JUMP_ABSOLUTE", 0))

        c = disassemble(func.__code__)
        sig = signature(func)

        find_pattern(c, fixed_opcode("LOAD_GLOBAL", func.__name__)
                     + StackEffectMatcher((c.code_info.co_argcount,), "argc")
                     + fixed_opcode("CALL_FUNCTION", Back("argc"))
                     + fixed_opcode("RETURN_VALUE"),
                     to_internal)
        func.__code__ = c.assemble()
        return func

    if func_or_none is None:
        return wrapper
    else:
        return wrapper(func_or_none)


def tail_call(func_or_none=None, /):
    def wrapper(func: FunctionType):
        def to_internal(bb: BasicBlock, r: MatchResult[Instruction]):
            assert r.end == len(bb.instructions)
            before = bb.instructions[:r.start]
            args = bb.instructions[r.start:r.end - 2]
            argc = r.captures["argc"]
            bound = sig.bind(*map(_OnStack, range(argc)))
            bound.apply_defaults()
            c.code_info.make_sure("consts", _Thunk)
            bb.instructions = before + [
                ins("LOAD_CONST", _Thunk),
            ] + args  + [
                ins("BUILD_TUPLE", argc),
                ins("BUILD_MAP", 0),
                ins("CALL_FUNCTION", 3),
                ins("RETURN_VALUE"),
            ]

        c = disassemble(func.__code__)
        sig = signature(func)

        find_pattern(c, fixed_opcode("LOAD_GLOBAL", capture_arg="function_name")
                     + StackEffectMatcher(lambda f: f >= 0, "argc")
                     + fixed_opcode("CALL_FUNCTION", Back("argc"))
                     + fixed_opcode("RETURN_VALUE"),
                     to_internal)
        func.__code__ = c.assemble()
        @wraps(func)
        def out(*args, **kwargs):
            return _force_tail(func(*args, **kwargs))
        out.__tail_call__ = func
        return out

    if func_or_none is None:
        return wrapper
    else:
        return wrapper(func_or_none)


class _Thunk(NamedTuple):
    func: Callable
    args: tuple
    kwargs: dict


def _force(v):  # This is not actually the code that will be executed. We just use it as a visual aid
    if isinstance(v, _Thunk):
        return _force(v.func(*v.args, **v.kwargs))
    return v


def _force_tail(v):  # This is not actually the code that will be executed. We just use it as a visual aid
    if isinstance(v, _Thunk):
        if hasattr(v.func, "__tail_call__"):
            return _force(v.func.__tail_call__(*v.args, **v.kwargs))
        else:
            return _force(v.func(*v.args, **v.kwargs))
    return v


def _build_force():
    assert "672a57622a606d71aff896c39d717578" == md5(_force.__code__.co_code).hexdigest(), md5(_force.__code__.co_code).hexdigest()
    c = disassemble(_force.__code__)
    test, rec_call, ret = c.blocks.values()
    test: BasicBlock
    rec_call: BasicBlock
    ret: BasicBlock
    assert isinstance(test.next_target, BasicBlockTarget) and test.next_target.target_id == rec_call.id

    c.code_info.make_sure("consts", _Thunk)
    c.code_info.make_sure("consts", ("kwargs", "args", "func"))
    test.instructions = [
        ins("LOAD_FAST", "v"),
        ins("LOAD_CONST", _Thunk),
        ins("LOAD_CONST", ("kwargs", "args", "func")),
        ins("MATCH_CLASS", 0)
    ]

    # test.Jump Instruction is already correct

    del ret.instructions[0]  # Because of MATCH_CLASS, TOS is already the correct value, no need for LOAD_FAST

    rec_call.instructions = [
        ins("UNPACK_SEQUENCE", 3),
        ins("CALL_FUNCTION_EX", 1),
    ]
    rec_call.jump_instruction = ins("JUMP_ABSOLUTE", BasicBlockTarget(test.id, 1))

    _force.__code__ = c.assemble()


def _build_force_tail():
    assert "ec2140b33ae9400bc6622efe6d5ce6b5" == md5(_force_tail.__code__.co_code).hexdigest(), md5(
        _force_tail.__code__.co_code).hexdigest()
    c = disassemble(_force_tail.__code__)
    test_thunk, test_tail, call_tail, call_normal, ret = c.blocks.values()
    test_thunk: BasicBlock
    test_tail: BasicBlock
    call_tail: BasicBlock
    call_normal: BasicBlock
    ret: BasicBlock
    assert isinstance(test_thunk.next_target, BasicBlockTarget) and test_thunk.next_target.target_id == test_tail.id
    assert isinstance(test_tail.next_target, BasicBlockTarget) and test_tail.next_target.target_id == call_tail.id
    assert isinstance(test_tail.jump_instruction.arg, BasicBlockTarget) and test_tail.jump_instruction.arg.target_id == call_normal.id
    assert isinstance(test_thunk.jump_instruction.arg, BasicBlockTarget) and test_thunk.jump_instruction.arg.target_id == ret.id

    c.code_info.make_sure("consts", _Thunk)
    c.code_info.make_sure("consts", ("func", "kwargs", "args"))
    c.code_info.make_sure("consts", object)
    c.code_info.make_sure("consts", ("__tail_call__",))

    test_thunk.instructions = [
        ins("LOAD_FAST", "v"),
        ins("LOAD_CONST", _Thunk),
        ins("LOAD_CONST", ("func", "kwargs", "args")),
        ins("MATCH_CLASS", 0)
    ]

    # test_thunk.Jump Instruction is already correct

    del ret.instructions[0]  # Because of MATCH_CLASS, TOS is already the correct value, no need for LOAD_FAST

    test_tail.instructions = [
        ins("UNPACK_SEQUENCE", 3),
        ins("LOAD_CONST", object),
        ins("LOAD_CONST", ("__tail_call__",)),
        ins("MATCH_CLASS", 0),
    ]
    # test_tail.Jump Instruction is already correct

    call_tail.instructions = [
        ins("UNPACK_SEQUENCE", 1),
    ]
    call_tail.next_target = BasicBlockTarget(call_normal.id, 0)
    call_normal.instructions = [
        ins("ROT_THREE"),
        ins("CALL_FUNCTION_EX", 1),
    ]
    call_normal.jump_instruction = ins("JUMP_ABSOLUTE", BasicBlockTarget(test_thunk.id, 1))

    _force_tail.__code__ = c.assemble()


_build_force()
_build_force_tail()
