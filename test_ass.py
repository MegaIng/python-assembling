from __future__ import annotations

import dis
import inspect
from operator import iadd, mul
from pprint import pprint
from time import time
from timeit import timeit

from basic_assembler import disassemble, nop
from inline_globals import inline_globals
import statistics


# @(lambda f: (dis.dis(f), f)[1])
@inline_globals
# @(lambda f: (dis.dis(f), f)[1])
def test(n):
    s = 0
    for i in range(n):
        for j in range(n):
            s = iadd(s, mul(i, j))
    return s


def print_timings(name, timings):
    mean = statistics.mean(timings)
    median = statistics.median(timings)
    print(f"{name:>10}: median={median:4.2f} mean={mean:4.2f}")


def measure(arg, n, m):
    with_res = []
    without_res = []
    with_code = test.__code__
    without_code = test.__orig_code__
    for _ in range(m):
        test.__code__ = with_code
        start = time()
        for _ in range(n):
            test(arg)
        end = time()
        with_res.append(end - start)

        test.__code__ = without_code
        start = time()
        for _ in range(n):
            test(arg)
        end = time()
        without_res.append(end - start)

        print_timings("without", without_res)
        print_timings("with", with_res)


dis.dis(test)
measure(1000, 50, 100)
