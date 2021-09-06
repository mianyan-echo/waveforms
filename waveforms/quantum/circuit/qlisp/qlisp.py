from __future__ import annotations

import warnings
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple, Optional, Union

from waveforms.waveform import Waveform, zero


def gateName(st):
    if isinstance(st[0], str):
        return st[0]
    else:
        return st[0][0]


class QLispError(SyntaxError):
    pass


class MeasurementTask(NamedTuple):
    qubit: str
    cbit: int
    time: float
    signal: str
    params: dict
    hardware: Union[ADChannel, MultADChannel] = None


class AWGChannel(NamedTuple):
    name: str
    sampleRate: float
    size: int = -1
    amplitude: Optional[float] = None
    offset: Optional[float] = None


class MultAWGChannel(NamedTuple):
    I: Optional[AWGChannel] = None
    Q: Optional[AWGChannel] = None
    LO: Optional[str] = None
    lo_freq: float = -1
    lo_power: Optional[float] = None


class ADChannel(NamedTuple):
    name: str
    sampleRate: float = 1e9
    trigger: str = ''
    triggerDelay: float = 0
    triggerClockCycle: float = 8e-9


class MultADChannel(NamedTuple):
    I: Optional[ADChannel] = None
    Q: Optional[ADChannel] = None
    IQ: Optional[ADChannel] = None
    Ref: Optional[ADChannel] = None
    LO: Optional[str] = None
    lo_freq: float = -1
    lo_power: Optional[float] = None


class GateConfig(NamedTuple):
    name: str
    qubits: tuple
    type: str = 'default'
    params: dict = {}


class ABCCompileConfigMixin(ABC):
    """
    Mixin for configs that can be used by compiler.
    """
    @abstractmethod
    def _getAWGChannel(self, name,
                       *qubits) -> Union[AWGChannel, MultAWGChannel]:
        pass

    @abstractmethod
    def _getADChannel(self, qubit) -> Union[ADChannel, MultADChannel]:
        pass

    @abstractmethod
    def _getGateConfig(self, name, *qubits) -> GateConfig:
        """
        Return the gate config for the given qubits.

        Args:
            name: Name of the gate.
            qubits: Qubits to which the gate is applied.
        
        Returns:
            GateConfig for the given qubits.
            if the gate is not found, return None.
        """
        pass

    @abstractmethod
    def _getAllQubitLabels(self) -> list[str]:
        pass


__config_factory = None


def set_config_factory(factory):
    global __config_factory
    __config_factory = factory


def getConfig() -> ABCCompileConfigMixin:
    if __config_factory is None:
        raise FileNotFoundError(
            'setConfig(path) or set_config_factory(factory) must be run first.'
        )
    else:
        return __config_factory()


@dataclass
class Context():
    cfg: ABCCompileConfigMixin = field(default_factory=getConfig)
    scopes: list[dict[str, Any]] = field(default_factory=lambda: [dict()])
    qlisp: list = field(default_factory=list)
    time: dict[str,
               float] = field(default_factory=lambda: defaultdict(lambda: 0))
    addressTable: dict = field(default_factory=dict)
    waveforms: dict[str, Waveform] = field(
        default_factory=lambda: defaultdict(zero))
    raw_waveforms: dict[tuple[str, ...], Waveform] = field(
        default_factory=lambda: defaultdict(zero))
    measures: dict[int, list[MeasurementTask]] = field(
        default_factory=lambda: defaultdict(list))
    phases: dict[str,
                 float] = field(default_factory=lambda: defaultdict(lambda: 0))
    biases: dict[str,
                 float] = field(default_factory=lambda: defaultdict(lambda: 0))
    end: float = 0

    @property
    def channel(self):
        return self.raw_waveforms

    @property
    def params(self):
        return self.scopes[-1]

    @property
    def vars(self):
        return self.scopes[-2]

    @property
    def globals(self):
        return self.scopes[0]

    def qubit(self, q):
        return self.addressTable[q]


@dataclass
class QLispCode():
    cfg: ABCCompileConfigMixin = field(repr=False)
    qlisp: list = field(repr=True)
    waveforms: dict[str, Waveform] = field(repr=True)
    measures: dict[int, list[MeasurementTask]] = field(repr=True)
    end: float = field(default=0, repr=True)
    signal: str = 'state'
    shots: int = 1024
    arch: str = 'general'


def set_context_factory(factory):
    warnings.warn('set_context_factory is deprecated', DeprecationWarning, 2)


def create_context(ctx: Optional[Context] = None, **kw) -> Context:
    if ctx is None:
        return Context(**kw)
    else:
        if 'cfg' not in kw:
            kw['cfg'] = ctx.cfg
        sub_ctx = Context(**kw)
        sub_ctx.time.update(ctx.time)
        sub_ctx.phases.update(ctx.phases)
        sub_ctx.biases.update(ctx.biases)

        return sub_ctx
