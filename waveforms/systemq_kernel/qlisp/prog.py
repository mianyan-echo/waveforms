from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional

from waveforms.qlisp import COMMAND, DataMap, QLispCode, Signal
from waveforms.scan_iter import StepStatus


@dataclass
class ProgramFrame():
    """
    A frame of a program.
    """
    step: StepStatus = field(default=None)
    circuit: list = field(default_factory=list)
    cmds: list[COMMAND] = field(default_factory=list)
    data_map: DataMap = field(default_factory=dict)
    code: Optional[QLispCode] = None
    context: dict = field(default_factory=dict)

    fut: Optional[asyncio.Future] = None

    def __getstate__(self):
        state = self.__dict__.copy()
        try:
            del state['fut']
        except:
            pass
        return state


@dataclass
class Program:
    """
    A program is a list of commands.
    """
    with_feedback: bool = False
    arch: str = 'baqis'

    side_effects: dict = field(default_factory=dict)

    steps: list[ProgramFrame] = field(default_factory=list)
    shots: int = 1024
    signal: Signal = Signal.state

    snapshot: dict = field(default_factory=dict)
    task_arguments: tuple[tuple, dict] = (tuple(), dict())
    meta_info: dict = field(default_factory=dict)
