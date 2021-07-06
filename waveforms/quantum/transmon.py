from functools import lru_cache

import numpy as np
from scipy.linalg import eigh_tridiagonal, eigvalsh_tridiagonal
from scipy.optimize import minimize
from waveforms.math.signal import complexPeaks


class Transmon():
    def __init__(self, **kw):
        self.Ec = 0.2
        self.EJ = 20

        self.d = 0
        if kw:
            self._set_params(**kw)

    def _set_params(self, **kw):
        if {"EJ", "Ec", "d"} <= set(kw):
            self._set_params_EJ_Ec_d(kw['EJ'], kw['Ec'], kw['d'])
        elif {"EJ", "Ec"} <= set(kw):
            self._set_params_EJ_Ec(kw['EJ'], kw['Ec'])
        elif {"f01", "alpha"} <= set(kw):
            if 'ng' not in kw:
                self._set_params_f01_alpha(kw['f01'], kw['alpha'])
            else:
                self._set_params_f01_alpha(kw['f01'], kw['alpha'], kw['ng'])
        else:
            raise TypeError(
                '_set_params() got an unexpected keyword arguments')

    def _set_params_EJ_Ec(self, EJ, Ec):
        self.Ec = Ec
        self.EJ = EJ

    def _set_params_EJ_Ec_d(self, EJ, Ec, d):
        self.Ec = Ec
        self.EJ = EJ
        self.d = d

    def _set_params_f01_alpha(self, f01, alpha, ng=0):
        Ec = -alpha
        EJ = (f01 - alpha)**2 / 8 / Ec

        def err(x, target=(f01, alpha)):
            EJ, Ec = x
            levels = self._levels(Ec, EJ, ng=ng)
            f01 = levels[1] - levels[0]
            f12 = levels[2] - levels[1]
            alpha = f12 - f01
            return (target[0] - f01)**2 + (target[1] - alpha)**2

        ret = minimize(err, x0=[EJ, Ec])
        self._set_params_EJ_Ec(*ret.x)

    def _set_params_f01_max_min_alpha(self, f01_max, f01_min, alpha, ng=0):
        Ec = -alpha
        EJ = (f01 - alpha)**2 / 8 / Ec

        def err(x, target=(f01, alpha)):
            EJ, Ec = x
            levels = self._levels(Ec, EJ, ng=ng)
            f01 = levels[1] - levels[0]
            f12 = levels[2] - levels[1]
            alpha = f12 - f01
            return (target[0] - f01)**2 + (target[1] - alpha)**2

        ret = minimize(err, x0=[EJ, Ec])
        self._set_params_EJ_Ec(*ret.x)

    @staticmethod
    def _flux_to_EJ(flux, EJS, d=0):
        F = np.pi * flux
        EJ = EJS * np.sqrt(np.cos(F)**2 + d**2 * np.sin(F)**2)
        return EJ

    @staticmethod
    def _levels(Ec, EJ, ng=0.0, gridSize=51, select_range=(0, 10)):
        n = np.arange(gridSize) - gridSize // 2
        w = eigvalsh_tridiagonal(4 * Ec * (n - ng)**2,
                                 -EJ / 2 * np.ones(gridSize - 1),
                                 select='i',
                                 select_range=select_range)
        return w

    @lru_cache(maxsize=128)
    def levels(self, flux=0, ng=0):
        return self._levels(self.Ec, self._flux_to_EJ(flux, self.EJ, self.d),
                            ng)

    def chargeParityDiff(self, flux=0, ng=0, k=0):
        a = self.levels(flux, ng=0 + ng)
        b = self.levels(flux, ng=0.5 + ng)

        return (a[1 + k] - a[k]) - (b[1 + k] - b[k])


class FakeQPU():
    def __init__(self,
                 N,
                 EJ=15e9,
                 Ec=220e6,
                 d=0.1,
                 EJ_error=0.01,
                 Ec_error=0.01,
                 zCrosstalkSigma=0.1,
                 seed=1234):
        np.random.seed(seed)
        self.N = N
        self.M = np.eye(N) + zCrosstalkSigma * np.random.randn(N, N)
        self.bias0 = np.random.randn(N)
        self.qubits = [
            Transmon(EJ=EJ * (1 + EJ_error * np.random.randn()),
                     Ec=Ec * (1 + Ec_error * np.random.randn()),
                     d=d) for i in range(N)
        ]
        self.fr = 6.5e9 + np.arange(N) * 20e6 + 3e6 * np.random.randn(N)
        self.g = 60e6 + 5e6 * np.random.randn(N)
        self.QL = 5000 + 100 * np.random.randn(N)
        self.Qc = 6000 + 100 * np.random.randn(N)
        self.Gamma = 0.03e6 + 1e3 * np.random.randn(N)
        self.readoutBias = np.zeros(N)
        self.driveBias = np.zeros(N)
        self.driveFrequency = np.zeros(N)
        self.driveOmega = np.zeros(N)
        self.driveDuration = np.zeros(N)
        self.readoutFrequency = np.zeros(N)
        self.fluxNoise = 0.001
        self.signalNoise = 0.05
        self.phi = 0.6 * np.random.randn(N)
        self.P1 = np.zeros(N)

    def fluxList(self, bias):
        return self.M @ bias + self.bias0 + self.fluxNoise * np.random.randn(
            self.N)

    def state(self):
        return [np.random.choice([0, 1], p=[1 - p1, p1]) for p1 in self.P1]

    def S21(self, x):
        fluxList = self.fluxList(self.readoutBias)
        state = self.state()
        levels = [q.levels(flux) for q, flux in zip(self.qubits, fluxList)]
        peaks = []
        for l, s, fr, g, QL, Qc, phi in zip(levels, state, self.fr, self.g,
                                            self.QL, self.Qc, self.phi):
            f01 = l[1] - l[0]
            f12 = l[2] - l[1]
            if s == 0:
                chi = g**2 / (f01 - fr)
            else:
                chi = 2 * g**2 / (f12 - fr) - g**2 / (f01 - fr)
            fc = fr - chi
            width = fc / (2 * QL)
            amp = -QL / np.abs(Qc) * np.exp(1j * phi)
            peaks.append((fc, width, amp))
        return complexPeaks(x, peaks, 1)

    @staticmethod
    def population(Omega, Delta, Gamma, t):
        return 0.5 * Omega / np.sqrt(Omega**2 + Delta**2) * (1 - np.exp(
            -4 / 3 * Gamma * t) * np.cos(np.sqrt(Omega**2 + Delta**2) * t))

    def calcP1(self):
        for i, (bias, freq, Omega, t) in enumerate(
                zip(self.driveBias, self.driveFrequency, self.driveOmega,
                    self.driveDuration)):
            q = self.qubits[i]
            l = q.levels(bias)
            Delta = freq - l[1] + l[0]
            self.P1[i] = self.population(Omega, Delta, self.Gamma[i], t)

    def signal(self):
        s = self.S21(self.readoutFrequency)
        return s + self.signalNoise * (np.random.randn(*s.shape) +
                                       1j * np.random.randn(*s.shape))


if __name__ == "__main__":
    q = Transmon(f01=4.2, alpha=4.010 - 4.2)

    levels = q.levels()
    f01 = levels[1] - levels[0]
    f12 = levels[2] - levels[1]

    print("chargeParityDiff:")
    for k in range(4):
        diff = q.chargeParityDiff(k=k)
        print(f"  ({k},{k+1}) diff = {diff * 1e3:8.4f} MHz",
              f"(T = {1/np.abs(diff) / 2e3:.1f} us)")
    print(
        f"EJ = {q.EJ:.4f} GHz, Ec = {q.Ec*1e3:.4f} MHz, EJ/Ec={q.EJ/q.Ec:.2f}")
    print(f"f01 = {f01:.4f} GHz, alpha = {(f12-f01)*1e3:.1f} MHz")
