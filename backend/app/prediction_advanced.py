from __future__ import annotations

from datetime import datetime, timezone
from math import sin, cos, pi
from typing import Any


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def cyclic_features(dt: datetime) -> list[float]:
    d = _aware(dt)
    hour = d.hour + d.minute / 60.0
    dow = d.weekday() + hour / 24.0
    return [
        1.0,
        sin(2*pi*hour/24.0), cos(2*pi*hour/24.0),
        sin(4*pi*hour/24.0), cos(4*pi*hour/24.0),
        sin(2*pi*dow/7.0), cos(2*pi*dow/7.0),
        1.0 if d.weekday() >= 5 else 0.0,
    ]


def _solve(a: list[list[float]], b: list[float]) -> list[float] | None:
    n = len(b)
    m = [list(map(float, a[i])) + [float(b[i])] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-12:
            return None
        if pivot != col:
            m[col], m[pivot] = m[pivot], m[col]
        div = m[col][col]
        m[col] = [v/div for v in m[col]]
        for r in range(n):
            if r == col:
                continue
            factor = m[r][col]
            if factor:
                m[r] = [m[r][c] - factor*m[col][c] for c in range(n+1)]
    return [m[i][-1] for i in range(n)]


def fit_cyclic_ridge(rows: list[Any], ridge: float = 0.35) -> dict[str, Any] | None:
    samples = [(cyclic_features(r.observed_at), float(r.congestion_index)) for r in rows if getattr(r, 'congestion_index', None) is not None]
    if len(samples) < 32:
        return None
    p = len(samples[0][0])
    xtx = [[0.0]*p for _ in range(p)]
    xty = [0.0]*p
    for x, y in samples:
        for i in range(p):
            xty[i] += x[i]*y
            for j in range(p):
                xtx[i][j] += x[i]*x[j]
    for i in range(1, p):
        xtx[i][i] += float(ridge)
    coef = _solve(xtx, xty)
    if coef is None:
        return None
    names = ['intercept','hour_sin1','hour_cos1','hour_sin2','hour_cos2','week_sin','week_cos','weekend']
    return {'coefficients': dict(zip(names, coef)), 'coefficient_vector': coef, 'samples': len(samples), 'ridge': ridge}


def predict_cyclic_ridge(model: dict[str, Any] | None, dt: datetime) -> float | None:
    if not model:
        return None
    coef = model.get('coefficient_vector') or []
    x = cyclic_features(dt)
    if len(coef) != len(x):
        return None
    return max(0.0, min(1.0, sum(float(c)*v for c, v in zip(coef, x))))
