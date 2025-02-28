# This code is part of Qiskit.
#
# (C) Copyright IBM 2017.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.
"""
=========================
Qasm (:mod:`qiskit.qasm`)
=========================
.. currentmodule:: qiskit.qasm
QASM Routines
=============
.. autosummary::
   :toctree: ../stubs/
   Qasm
   QasmError
Pygments
========
.. autosummary::
   :toctree: ../stubs/
   OpenQASMLexer
   QasmHTMLStyle
   QasmTerminalStyle
"""

from numpy import pi

from .eval import qasm_eval
from .exceptions import QasmError
from .qasm import Qasm

try:
    import pygments
    HAS_PYGMENTS = True
except ImportError:
    HAS_PYGMENTS = False

if HAS_PYGMENTS:
    try:
        from .pygments import OpenQASMLexer, QasmHTMLStyle, QasmTerminalStyle
    except Exception:  # pylint: disable=broad-except
        HAS_PYGMENTS = False
