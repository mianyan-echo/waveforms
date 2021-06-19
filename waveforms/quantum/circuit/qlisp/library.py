from __future__ import annotations

from functools import wraps
from inspect import signature
from typing import Callable, Iterable, Optional, Union

from .qlisp import Context


def gate(qnum: int = 1, name: Optional[str] = None, scope: dict = None):
    def decorator(func: Callable[..., Iterable], name: str = name):
        if name is None:
            name = func.__name__
        sig = signature(func)
        anum = len(sig.parameters) - 1
        if 'scope' in sig.parameters:
            anum -= 1

        @wraps(func)
        def wrapper(qubits: Union[int, tuple[int, ...]],
                    *args,
                    scope: dict = scope,
                    **kwds):
            if isinstance(qubits, (int, str)):
                if qnum != 1:
                    raise TypeError(
                        f"gate {name} should be {qnum}-qubit gate, but 1 were given."
                    )
            elif len(qubits) != qnum:
                raise TypeError(
                    f"gate {name} should be {qnum}-qubit gate, but {len(qubits)} were given."
                )
            if len(args) + len(kwds) != anum:
                raise TypeError(
                    f"gate {name} should be {anum}-arguments gate, but {len(args)+len(kwds)} were given."
                )
            if 'scope' in sig.parameters:
                kwds['scope'] = scope
            return func(qubits, *args, **kwds)

        scope[name] = wrapper
        return wrapper

    return decorator


def opaque(name: str,
           type: str = 'default',
           scope: dict[str, dict[str, Callable]] = None):
    def decorator(func: Callable[..., None], name: str = name):
        sig = signature(func)

        @wraps(func)
        def wrapper(ctx: Context, qubits, *args, **kwds):
            if 'scope' in sig.parameters:
                kwds['scope'] = scope
            return func(ctx, qubits, *args, **kwds)

        if name not in scope:
            scope[name] = {}
        scope[name][type] = wrapper
        return wrapper

    return decorator


class Library():
    def __init__(self):
        self.parents: tuple[Library, ...] = ()
        self.gates = {}
        self.opaques = {}
        self.qasmLib = {}

    def gate(self, qnum: int = 1, name: Optional[str] = None):
        return gate(qnum=qnum, name=name, scope=self.gates)

    def opaque(self, name: str, type: str = 'default'):
        return opaque(name, type=type, scope=self.opaques)

    def getGate(self, name: str):
        gate = self.gates.get(name, None)
        if gate is None and len(self.parents) > 0:
            for lib in self.parents:
                gate = lib.getGate(name)
                if name is not None:
                    break
        return gate

    def getOpaque(self, name: str, type: str = 'default'):
        if name in self.opaques:
            opaque = self.opaques[name].get(type, None)
        else:
            opaque = None
        if opaque is None and len(self.parents) > 0:
            for lib in self.parents:
                opaque = lib.getOpaque(name, type)
                if opaque is not None:
                    break
        return opaque

    def getQasmLib(self, name: str):
        incfile = self.qasmLib.get(name, None)
        if incfile is None and len(self.parents) > 0:
            for lib in self.parents:
                incfile = lib.getQasmLib(name)
                if name is not None:
                    break
        return incfile


def libraries(*libs: Library) -> Library:
    ret = Library()
    ret.parents = libs
    return ret
