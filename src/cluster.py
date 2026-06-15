"""Cross-source story clustering — pure-Python, no ML deps.

Groups articles that report the *same event* (e.g. an oil move covered by 3
outlets) so the site shows one card with an "also covered by" source list,
instead of near-duplicate entries.

Scoring is normalized term-frequency cosine over *stemmed headline tokens*,
with NO inverse-document-frequency weighting. IDF was tried and hurt: within a
single day's batch the shared event keywords (e.g. "iran", "deal") appear in
many stories, so IDF down-weights exactly the terms that should bind dupes
together. Plain TF on headlines keeps that signal. Callers should cluster
*within a topic* to avoid merging different angles of one mega-event (oil-down
vs stocks-up). Heavy paraphrases still won't merge — that needs semantic
embeddings (a future upgrade once an embedding API is wired in).
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Callable

_TOKEN = re.compile(r"[A-Za-z0-9$%]+")
_STOP = set(
    "the a an and or but of to in on for with at by from is are was were be been "
    "being it its this that these those as he she they we you i his her their our "
    "will would could should can may might must has have had do does did not no "
    "than then over under after before about into out up down new says said amid "
    "more most less via per us".split()
)


def _stem(t: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if len(t) > 4 and t.endswith(suf):
            return t[: -len(suf)]
    return t


def _tokens(text: str) -> list[str]:
    return [_stem(t) for t in (w.lower() for w in _TOKEN.findall(text or ""))
            if len(t) > 1 and t not in _STOP]


def _tf_vector(tokens: list[str]) -> dict[str, float]:
    if not tokens:
        return {}
    tf = Counter(tokens)
    n = len(tokens)
    vec = {t: c / n for t, c in tf.items()}
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return {t: v / norm for t, v in vec.items()}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(t, 0.0) for t, v in a.items())


def cluster(items: list, text_fn: Callable[[object], str],
            threshold: float = 0.40) -> list[list]:
    """Greedy single-pass clustering. Returns clusters (lists of items).

    Each item is compared against existing cluster representatives (the first
    member of each cluster — conservative, limits chaining); if its best cosine
    clears `threshold` it joins, else it seeds a new cluster. Input order is
    preserved within clusters.
    """
    vecs = [_tf_vector(_tokens(text_fn(it))) for it in items]
    clusters: list[list[int]] = []
    reps: list[dict[str, float]] = []
    for i, v in enumerate(vecs):
        best_ci, best_sim = -1, 0.0
        for ci, rep in enumerate(reps):
            s = _cosine(v, rep)
            if s > best_sim:
                best_sim, best_ci = s, ci
        if best_ci >= 0 and best_sim >= threshold:
            clusters[best_ci].append(i)
        else:
            clusters.append([i])
            reps.append(v)
    return [[items[i] for i in members] for members in clusters]
