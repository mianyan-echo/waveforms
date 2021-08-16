import asyncio
import functools
import itertools
import logging
import os
import threading
import time
import uuid
import warnings
import weakref
from abc import ABC, abstractmethod
from collections import deque
from pathlib import Path
from typing import Any, Optional, Union

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.pool import SingletonThreadPool
from waveforms.quantum.circuit.qlisp.config import Config
from waveforms.quantum.circuit.qlisp.library import Library
from waveforms.storage.models import User, create_tables
from waveforms.waveform import Waveform

from .base import COMMAND, READ, WRITE
from .scan_iters import scan_iters
from .task import Task, create_task

log = logging.getLogger(__name__)


class Executor(ABC):
    @property
    def log(self):
        return logging.getLogger(
            f"{self.__module__}.{self.__class__.__name__}")

    @abstractmethod
    def feed(self, task_id: int, task_step: int, cmds: list[COMMAND],
             extra: dict):
        """
        """
        pass

    @abstractmethod
    def free(self, task_id: int) -> None:
        pass

    @abstractmethod
    def submit(self, task_id: int, data_template: dict) -> None:
        pass

    @abstractmethod
    def fetch(self, task_id: int, skip: int = 0) -> list:
        pass

    @abstractmethod
    def save(self, path: str, task_id: int, data: dict) -> str:
        pass


class _ThreadWithKill(threading.Thread):
    def __init__(self, *args, **kwds):
        super().__init__(*args, **kwds)
        self._kill_event = threading.Event()

    def kill(self):
        self._kill_event.set()


def _is_finished(task: Task) -> bool:
    """Check if a task is finished."""
    if task.kernel is None:
        return False
    finished_step = len(task.result()['data'])
    return task.status not in [
        'submiting', 'pending'
    ] and finished_step >= task.runtime.step or task.status in [
        'canceled', 'finished'
    ]


def join_task(task: Task, executor: Executor):
    try:
        while True:
            if threading.current_thread()._kill_event.is_set():
                break
            time.sleep(1)

            if _is_finished(task):
                executor.save(task.id, task.data_path)
                task.runtime.finished_time = time.time()
                if task.runtime.record is not None:
                    try:
                        task.runtime.record.data = task.result()
                        task.db.commit()
                    except Exception as e:
                        log.error(f"Failed to save record: {e}")
                else:
                    log.warning(f"No record for task {task.name}({task.id})")
                break
    except:
        log.exception(f"{task.name}({task.id}) is failed")
        executor.free(task.id)
    finally:
        log.debug(f'{task.name}({task.id}) is finished')
        clean_side_effects(task, executor)


def clean_side_effects(task: Task, executor: Executor):
    cmds = []
    for k, v in task.runtime.prog.side_effects.items():
        cmds.append(WRITE(k, v))
        executor.update(k, v, cache=False)
    executor.feed(task.id, -1, cmds)
    task.cfg.clear_buffer()


def exec_circuit(task: Task, circuit: Union[str, list], lib: Library,
                 cfg: Config, signal: str, compile_once: bool) -> int:
    """Execute a circuit."""
    from waveforms import compile
    from waveforms.backends.quark.executable import getCommands

    task.runtime.prog.steps[-1] = (circuit, {}, [])
    if task.runtime.step == 0 or not compile_once:
        code = compile(circuit, lib=lib, cfg=cfg)
        cmds, dataMap = getCommands(code, signal=signal, shots=task.shots)
        task.runtime.cmds.extend(cmds)
        task.runtime.prog.data_maps[-1].update(dataMap)
    else:
        for cmd in task.runtime.prog.commands[-1]:
            if (isinstance(cmd, READ) or cmd.address.endswith('.StartCapture')
                    or cmd.address.endswith('.CaptureMode')):
                task.runtime.cmds.append(cmd)
        task.runtime.prog.data_maps[-1] = task.runtime.prog.data_maps[0]
    return task.runtime.step


def submit_loop(task_queue: deque, current_stack: list[tuple[Task,
                                                             _ThreadWithKill]],
                running_pool: dict[int, tuple[Task, _ThreadWithKill]],
                executor: Executor):
    while True:
        if len(current_stack) > 0:
            current_task, thread = current_stack.pop()

            if thread.is_alive():
                current_stack.append((current_task, thread))
            else:
                current_task.runtime.status = 'running'

        try:
            task = task_queue.popleft()
        except IndexError:
            time.sleep(1)
            continue

        if (len(current_stack) == 0
                or task.is_children_of(current_stack[-1][0])):
            submit(task, current_stack, running_pool, executor)
        else:
            task_queue.appendleft(task)


def submit(task: Task, current_stack: list[tuple[Task, _ThreadWithKill]],
           running_pool: dict[int, tuple[Task, _ThreadWithKill]],
           executor: Executor):
    executor.free(task.id)
    task.runtime.status = 'submiting'
    submit_thread = _ThreadWithKill(target=task.main)
    current_stack.append((task, submit_thread))
    task.runtime.started_time = time.time()
    submit_thread.start()

    fetch_data_thread = _ThreadWithKill(target=join_task,
                                        args=(task, executor))
    running_pool[task.id] = task, fetch_data_thread
    fetch_data_thread.start()


def waiting_loop(running_pool: dict[int, tuple[Task, _ThreadWithKill]],
                 debug_mode: bool = False):
    while True:
        for taskID, (task, thread) in list(running_pool.items()):
            if not thread.is_alive():
                try:
                    if not debug_mode:
                        del running_pool[taskID]
                except:
                    pass
                task.runtime.status = 'finished'
        time.sleep(0.01)


def expand_task(task: Task, executor: Executor):
    task.runtime.step = 0
    task.runtime.prog.index = []
    task.runtime.prog.commands = []
    task.runtime.prog.data_maps = []
    task.runtime.prog.side_effects = {}
    task.runtime.prog.steps = []
    task.runtime.prog.shots = task.shots
    task.runtime.prog.signal = task.signal

    iters = task.scan_range()
    for step in scan_iters(iters):
        try:
            if threading.current_thread()._kill_event.is_set():
                break
        except AttributeError:
            pass

        task.runtime.prog.index.append(step)
        task.runtime.prog.data_maps.append({})
        task.runtime.prog.steps.append(([], {}, []))

        for k, v in step.kwds.items():
            if k in task.runtime.result['index']:
                task.runtime.result['index'][k].append(v)
            else:
                task.runtime.result['index'][k] = [v]

        task.runtime.cmds = []
        yield step
        task.trig()
        cmds = task.runtime.cmds
        task.runtime.prog.commands.append(task.runtime.cmds)

        for k, v in task.cfg._history.items():
            task.runtime.prog.side_effects.setdefault(k, v)

        executor.feed(task.id, task.runtime.step, cmds, extra={})
        for cmd in cmds:
            if isinstance(cmd.value, Waveform):
                task.runtime.prog.side_effects[cmd.address] = 'zero()'
        task.runtime.step += 1


class Scheduler():
    def __init__(self,
                 executor: Executor,
                 url: Optional[str] = None,
                 data_path: Union[str, Path] = Path.home() / 'data',
                 debug_mode: bool = False):
        """
        Parameters
        ----------
        executor : Executor
            The executor to use to submit tasks
        url : str
            The url of the database. These URLs follow RFC-1738, and usually
            can include username, password, hostname, database name as well
            as optional keyword arguments for additional configuration.
            In some cases a file path is accepted, and in others a "data
            source name" replaces the "host" and "database" portions. The
            typical form of a database URL is:
                `dialect+driver://username:password@host:port/database`
        """
        self.counter = itertools.count()
        self.__uuid = uuid.uuid1()
        self._task_pool = {}
        self._queue = deque()
        self._waiting_pool = {}
        self._submit_stack = []
        self.mutex = set()
        self.executor = executor
        if url is None:
            url = 'sqlite:///{}'.format(data_path / 'waveforms.db')
        self.db = url
        self.data_path = Path(data_path)
        self.eng = create_engine(url,
                                 echo=debug_mode,
                                 poolclass=SingletonThreadPool,
                                 connect_args={'check_same_thread': False})
        if (self.db == 'sqlite:///:memory:' or self.db.startswith('sqlite:///')
                and not os.path.exists(self.db.removeprefix('sqlite:///'))):
            create_tables(self.eng)

        self.system_user = self.login('BIG BROTHER', self.__uuid)

        self._read_data_thread = threading.Thread(target=waiting_loop,
                                                  args=(self._waiting_pool,
                                                        debug_mode),
                                                  daemon=True)
        self._read_data_thread.start()

        self._submit_thread = threading.Thread(
            target=submit_loop,
            args=(self._queue, self._submit_stack, self._waiting_pool,
                  self.executor),
            daemon=True)
        self._submit_thread.start()

    def login(self, username: str, password: str) -> User:
        db = self.session()
        if username == 'BIG BROTHER' and password == self.__uuid:
            try:
                user = db.query(User).filter(User.name == username).one()
            except NoResultFound:
                user = User(name=username)
                db.add(user)
                db.commit()
        else:
            try:
                user = db.query(User).filter(User.name == username).one()
            except NoResultFound:
                raise ValueError('User not found')
            if not user.verify(password):
                raise ValueError('Wrong password')
        return user

    @property
    def cfg(self):
        return self.executor.cfg

    @property
    def executer(self):
        warnings.warn(
            'kernel.executer is deprecated, use kernel.executor instead',
            DeprecationWarning)
        return self.executor

    def session(self):
        return sessionmaker(bind=self.eng)()

    def get_task_by_id(self, task_id):
        try:
            return self._task_pool.get(task_id)()
        except:
            return None

    def cancel(self):
        self.executor.cancel()
        self._queue.clear()
        while self._submit_stack:
            task, thread = self._submit_stack.pop()
            thread.kill()
            task.runtime.status = 'canceled'

        while self._waiting_result:
            task_id, (task, thread) = self._waiting_result.popitem()
            thread.kill()
            task.runtime.status = 'canceled'

    def join(self, task):
        while True:
            if task.status == 'finished':
                break
            time.sleep(1)

    def set(self, key: str, value: Any, cache: bool = False):
        cmds = []
        if not cache:
            cmds.append(WRITE(key, value))
        if len(cmds) > 0:
            self.executor.feed(0, -1, cmds)
            self.executor.free(0)
        self.cfg.update(key, value, cache=cache)

    def get(self, key: str):
        """
        return the value of the key in the kernel config
        """
        return self.query(key)

    async def join_async(self, task):
        while True:
            if task.status == 'finished':
                break
            await asyncio.sleep(1)

    def generate_task_id(self):
        i = uuid.uuid3(self.__uuid, f"{next(self.counter)}").int
        return i & ((1 << 64) - 1)

    def scan(self, task):
        """Yield from task.scan_range().

        :param task: task to scan
        :return: a generator yielding step arguments.
        """
        yield from expand_task(task, self.executor)

    def _exec(self,
              task,
              circuit,
              lib=None,
              cfg=None,
              signal='state',
              compile_once=False):
        """Execute a circuit."""
        from waveforms import stdlib

        if lib is None:
            lib = stdlib
        if cfg is None:
            cfg = self.cfg

        return exec_circuit(task,
                            circuit,
                            lib=lib,
                            cfg=cfg,
                            signal=signal,
                            compile_once=compile_once)

    def exec(self, circuit, lib=None, cfg=None, signal='state', cmds=[]):
        """Execute a circuit.
        
        Parameters:
            circuit: a QLisp Circuit.
            lib: a Library used by compiler,default is stdlib.
            cfg: configuration of system.
            signal: a str of the name of the signal type to be returned.
            cmds: additional commands.

        Returns:
            A Task.
        """
        from waveforms.sched import App

        class A(App):
            def scan_range(self):
                yield 0

            def main(self):
                for _ in self.scan():
                    self.runtime.cmds.extend(cmds)
                    self.exec(circuit, lib=lib, cfg=cfg)

        t = A()
        t.signal = signal
        self.submit(t)
        return t

    def _measure(self, task, keys, labels=None):
        if labels is None:
            labels = keys
        dataMap = {label: key for key, label in zip(keys, labels)}
        task.runtime.prog.data_maps[-1].update(dataMap)
        cmds = [(key, READ) for key in keys]
        task.runtime.cmds.extend(cmds)

    def measure(self, keys, labels=None, cmds=[]):
        pass

    def update_parameters(self, parameters: dict[str, Any]):
        """Update parameters.

        Args:
            parameters: a dict of parameters.
        """
        for key, value in parameters.items():
            self.update(key, value)
        self.cfg.clear_buffer()

    def maintain(self, task: Task) -> Task:
        """Maintain a task.
        """
        from ._bigbrother import maintain

        return maintain(self, task)

    def fetch(self, task: Task, skip: int = 0) -> list[dict]:
        """Fetch result of task from the executor, skip the
        first `skip` steps.

        Args:
            task: a task.
            skip: the number of steps to skip.

        Returns:
            A list of dicts.
        """
        return self.executor.fetch(task.id, skip)

    def submit(self, task: Task) -> Task:
        """Submit a task.
        """
        if task.status != 'not submited':
            raise RuntimeError(
                f'Task({task.id}, status={task.status}) has been submited!')
        taskID = self.generate_task_id()
        task._set_kernel(self, taskID)
        task.runtime.status = 'pending'
        self._queue.append(task)

        def delete(ref, dct, key):
            dct.pop(key)

        self._task_pool[task.id] = weakref.ref(
            task, functools.partial(delete, dct=self._task_pool, key=task.id))
        return task

    def query(self, key):
        return self.cfg.query(key)

    def update(self, key, value, cache=False):
        self.executor.update(key, value, cache=cache)

    def create_task(self, app, args=(), kwds={}):
        """
        create a task from a string or a class

        Args:
            app: a string or a class
            args: arguments for the class
            kwds: keyword arguments for the class
        
        Returns:
            a task
        """
        task = create_task((app, args, kwds))
        task._set_kernel(self, -1)
        return task
