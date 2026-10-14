"""Answer grounding checks: every material number must come from tool evidence and be cited."""

from __future__ import annotations

import re

NUM = re.compile(r"(?<![\w.])[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])[-+]?\d+(?:\.\d+)?")
CITE = re.compile(r"\[(E\d+)\]")
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\[])")


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _collect(values: object, out: list[float]) -> None:
    if isinstance(values, bool) or values is None:
        return
    if isinstance(values, int | float):
        out.append(float(values))
    elif isinstance(values, dict):
        for v in values.values():
            _collect(v, out)
    elif isinstance(values, list | tuple):
        for v in values:
            _collect(v, out)


def check(answer: str, evidence: list[dict], extra_allowed: list[float] | None = None) -> dict:
    """Return {passed, unsupported_numbers, uncited_sentences, unknown_citations}.

    Numbers that are years (1900-2100), list ordinals 1-10, or appear in the question context
    (extra_allowed) are exempt. Rounding to the displayed precision is tolerated.
    """
    by_id = {e["id"]: e for e in evidence}
    allowed: list[float] = list(extra_allowed or [])
    for e in evidence:
        _collect(e.get("values"), allowed)
    unsupported, uncited, unknown = [], [], []
    for sent in SENTENCE.split(answer):
        nums = [m.group(0) for m in NUM.finditer(CITE.sub("", sent))]
        cites = CITE.findall(sent)
        unknown += [c for c in cites if c not in by_id]
        material = []
        for raw in nums:
            v = _num(raw)
            if (1900 <= v <= 2100 and float(v).is_integer()) or (0 <= v <= 10 and float(v).is_integer()):
                continue
            material.append(raw)
            decimals = len(raw.split(".")[1]) if "." in raw else 0
            tol = 0.5 * 10 ** (-decimals) + 1e-9
            if not any(abs(v - a) <= tol or abs(abs(v) - abs(a)) <= tol for a in allowed):
                unsupported.append(raw)
        if material and not cites:
            uncited.append(sent.strip()[:200])
    return {
        "passed": not (unsupported or uncited or unknown),
        "unsupported_numbers": unsupported,
        "uncited_sentences": uncited,
        "unknown_citations": sorted(set(unknown)),
    }
