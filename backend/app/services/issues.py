"""Aggregate issue analysis over licensed/permitted text.

Scope (docs/methodology/issue-analysis.md):
  * Measures how often topics appear in covered sources (topic *frequency*), by period
    and geography, with source coverage and geographic confidence shown alongside.
  * Does NOT measure sentiment, support or voting intention; the platform has no validated
    model for those and topic frequency in text is not population opinion.
  * Outputs are aggregates with a minimum cell size; no author-level data is stored.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Document, DocumentTopic, ModelVersion, Source, Topic, TopicLabel

TAXONOMY_VERSION = "2026.1"
CLASSIFIER_VERSION = "lexicon-1.0.0"
MIN_CELL = 5

STOPWORDS = {
    "en": (
        "the and of to in is that for it with as was on are be this by have from or not but they his her at " "which"
    ).split(),
    "es": (
        "el la de que y en los se del las un por con no una su para es al lo como más pero sus le ya o fue " "este"
    ).split(),
    "fr": "le la les de des et est un une du en que qui dans pour pas sur au avec ce il elle sont".split(),
    "de": "der die das und ist nicht ein eine zu den von mit sich des auf für im dem auch es an".split(),
    "pt": "o a os as de do da dos das e que em um uma para com não se na no por mais é".split(),
}
_word = re.compile(r"[a-záéíóúñüçàèâêôãõäöß']+", re.I)
_sentence = re.compile(r"(?<=[.!?])\s+")

# Lexicon topic taxonomy. Phrases are matched on word boundaries, case-insensitively.
TOPICS: dict[str, dict] = {
    "economy": {
        "label": "Economy and cost of living",
        "en": [
            "inflation",
            "cost of living",
            "prices",
            "jobs",
            "unemployment",
            "wages",
            "economy",
            "tariff",
            "tariffs",
            "interest rates",
            "grocery",
        ],
        "es": ["inflación", "costo de vida", "precios", "empleo", "desempleo", "salarios", "economía", "aranceles"],
    },
    "immigration": {
        "label": "Immigration and border",
        "en": ["immigration", "border", "asylum", "deportation", "migrants", "visa"],
        "es": ["inmigración", "frontera", "asilo", "deportación", "migrantes"],
    },
    "health": {
        "label": "Health care",
        "en": ["health care", "healthcare", "medicare", "medicaid", "insurance premiums", "hospital", "prescription"],
        "es": ["salud", "atención médica", "seguro médico", "hospital", "medicamentos"],
    },
    "reproductive": {
        "label": "Abortion and reproductive rights",
        "en": ["abortion", "reproductive rights", "ivf"],
        "es": ["aborto", "derechos reproductivos"],
    },
    "public_safety": {
        "label": "Crime and public safety",
        "en": ["crime", "police", "public safety", "violence", "shooting", "fentanyl"],
        "es": ["crimen", "policía", "seguridad pública", "violencia"],
    },
    "democracy": {
        "label": "Democracy and election administration",
        "en": [
            "election officials",
            "voting rights",
            "ballot access",
            "redistricting",
            "gerrymander",
            "certification",
            "mail ballots",
        ],
        "es": ["derecho al voto", "redistribución", "funcionarios electorales", "boletas por correo"],
    },
    "climate": {
        "label": "Climate, energy and environment",
        "en": ["climate", "energy", "emissions", "wildfire", "drought", "renewable", "gas prices"],
        "es": ["clima", "energía", "emisiones", "incendios", "sequía"],
    },
    "education": {
        "label": "Education",
        "en": ["schools", "teachers", "education", "student loans", "tuition"],
        "es": ["escuelas", "maestros", "educación", "préstamos estudiantiles"],
    },
    "housing": {
        "label": "Housing",
        "en": ["housing", "rent", "mortgage", "homelessness", "affordable homes"],
        "es": ["vivienda", "alquiler", "renta", "hipoteca"],
    },
    "foreign_policy": {
        "label": "Foreign policy and security",
        "en": ["foreign policy", "ukraine", "nato", "china", "military aid", "war"],
        "es": ["política exterior", "guerra", "ayuda militar"],
    },
}
_topic_patterns = {
    k: re.compile(r"\b(" + "|".join(re.escape(t) for lang in ("en", "es") for t in v[lang]) + r")\b", re.I)
    for k, v in TOPICS.items()
}


def detect_languages(text: str) -> tuple[str, dict[str, float]]:
    """Sentence-level stopword voting; returns (primary or 'mixed', proportions)."""
    votes: Counter[str] = Counter()
    for sent in _sentence.split(text):
        words = [w.lower() for w in _word.findall(sent)]
        if len(words) < 3:
            continue
        scores = {lang: sum(w in sw for w in words) for lang, sw in STOPWORDS.items()}
        best = max(scores, key=scores.get)  # type: ignore[arg-type]
        if scores[best] > 0:
            votes[best] += len(words)
    total = sum(votes.values())
    if not total:
        return "und", {}
    props = {k: round(v / total, 3) for k, v in votes.most_common()}
    ranked = list(props.items())
    if len(ranked) > 1 and ranked[1][1] >= 0.25:
        return "mixed", props
    return ranked[0][0], props


def normalize_text(text: str) -> str:
    return " ".join(_word.findall(text.lower()))


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode()).hexdigest()


_P = (1 << 61) - 1
_rng = np.random.default_rng(20261014)
_A = _rng.integers(1, _P, size=64, dtype=np.uint64)
_B = _rng.integers(0, _P, size=64, dtype=np.uint64)


def minhash(text: str, k: int = 5) -> list[int]:
    words = normalize_text(text).split()
    shingles = {" ".join(words[i : i + k]) for i in range(max(1, len(words) - k + 1))}
    if not shingles:
        return []
    hv = np.array(
        [int.from_bytes(hashlib.blake2b(s.encode(), digest_size=7).digest(), "big") for s in shingles], dtype=np.uint64
    )
    # (a*x + b) mod p computed in Python ints to avoid uint64 overflow.
    sig = [min(((int(a) * int(x) + int(b)) % _P) for x in hv) for a, b in zip(_A, _B, strict=True)]
    return sig


def jaccard_estimate(a: list[int], b: list[int]) -> float:
    if not a or not b:
        return 0.0
    return sum(x == y for x, y in zip(a, b, strict=False)) / len(a)


def classify(text: str) -> dict[str, float]:
    """Return topic -> score (matches per 100 words, capped at 1.0) for topics over threshold."""
    words = max(1, len(_word.findall(text)))
    out = {}
    for key, pat in _topic_patterns.items():
        hits = len(pat.findall(text))
        if hits >= 2 or (hits == 1 and words < 120):
            out[key] = round(min(1.0, hits * 100 / words / 5), 3)
    return out


def ensure_taxonomy(db: Session) -> tuple[dict[str, Topic], ModelVersion]:
    topics = {t.key: t for t in db.scalars(select(Topic).where(Topic.taxonomy_version == TAXONOMY_VERSION))}
    for key, spec in TOPICS.items():
        if key not in topics:
            t = Topic(taxonomy_version=TAXONOMY_VERSION, key=key, label=spec["label"])
            db.add(t)
            topics[key] = t
    mv = db.scalar(
        select(ModelVersion).where(ModelVersion.kind == "topic_classifier", ModelVersion.version == CLASSIFIER_VERSION)
    )
    if mv is None:
        mv = ModelVersion(
            kind="topic_classifier",
            version=CLASSIFIER_VERSION,
            description="Bilingual (en/es) lexicon classifier; taxonomy " + TAXONOMY_VERSION,
            params={"taxonomy": TAXONOMY_VERSION, "threshold": "2 hits, or 1 hit in <120 words"},
        )
        db.add(mv)
    db.flush()
    return topics, mv


def classify_documents(db: Session, doc_ids: list | None = None) -> int:
    topics, mv = ensure_taxonomy(db)
    done = select(DocumentTopic.document_id).where(DocumentTopic.model_version_id == mv.id)
    q = select(Document).where(Document.duplicate_of_id.is_(None), Document.id.not_in(done))
    if doc_ids:
        q = q.where(Document.id.in_(doc_ids))
    n = 0
    for doc in db.scalars(q):
        for key, score in classify(f"{doc.title}. {doc.body}").items():
            db.add(DocumentTopic(document_id=doc.id, topic_id=topics[key].id, model_version_id=mv.id, score=score))
        n += 1
    db.flush()
    return n


@dataclass
class EvalResult:
    per_topic: dict[str, dict]
    micro: dict
    n_documents: int
    model_version: str
    labeled_by_synthetic_only: bool


def evaluate(db: Session, split: str = "eval") -> EvalResult:
    """Compare classifier output against human labels (TopicLabel)."""
    topics, mv = ensure_taxonomy(db)
    by_id = {t.id: t.key for t in topics.values()}
    labels = db.execute(
        select(TopicLabel.document_id, TopicLabel.topic_id, TopicLabel.is_relevant).where(TopicLabel.split == split)
    ).all()
    gold: dict = defaultdict(dict)
    for doc_id, topic_id, rel in labels:
        gold[doc_id][by_id.get(topic_id)] = rel
    docs = {d.id: d for d in db.scalars(select(Document).where(Document.id.in_(list(gold))))}
    synth_sources = {s.id for s in db.scalars(select(Source).where(Source.is_synthetic.is_(True)))}
    counts: dict[str, Counter] = defaultdict(Counter)
    for doc_id, g in gold.items():
        doc = docs.get(doc_id)
        if doc is None:
            continue
        pred = classify(f"{doc.title}. {doc.body}")
        for topic, rel in g.items():
            p = topic in pred
            counts[topic]["tp" if p and rel else "fp" if p and not rel else "fn" if rel else "tn"] += 1
    per_topic = {}
    tot: Counter = Counter()
    for topic, c in counts.items():
        tot.update(c)
        per_topic[topic] = _prf(c)
    return EvalResult(
        per_topic,
        _prf(tot),
        len(gold),
        mv.version,
        bool(docs) and all(d.source_id in synth_sources for d in docs.values()),
    )


def _prf(c: Counter) -> dict:
    p = c["tp"] / (c["tp"] + c["fp"]) if c["tp"] + c["fp"] else None
    r = c["tp"] / (c["tp"] + c["fn"]) if c["tp"] + c["fn"] else None
    f = 2 * p * r / (p + r) if p and r else None
    return {"precision": p, "recall": r, "f1": f, "support": c["tp"] + c["fn"], **dict(c)}


def topic_trends(
    db: Session,
    *,
    country: str,
    start: datetime,
    end: datetime,
    admin_unit_id=None,  # type: ignore[no-untyped-def]
    bucket: str = "week",
) -> dict:
    """Weekly topic frequency (share of covered, de-duplicated documents mentioning the topic)."""
    _, mv = ensure_taxonomy(db)
    base = select(
        Document.id, Document.published_at, Document.source_id, Document.geo_confidence, Document.language
    ).where(
        Document.country_code == country,
        Document.published_at >= start,
        Document.published_at < end,
        Document.duplicate_of_id.is_(None),
    )
    if admin_unit_id:
        base = base.where(Document.admin_unit_id == admin_unit_id)
    docs = db.execute(base).all()

    def trunc(dt: datetime) -> str:
        return (dt - timedelta(days=dt.weekday())).date().isoformat() if bucket == "week" else dt.date().isoformat()

    denom: Counter = Counter(trunc(d.published_at) for d in docs)
    doc_bucket = {d.id: trunc(d.published_at) for d in docs}
    rows = (
        db.execute(
            select(DocumentTopic.document_id, Topic.key)
            .join(Topic, Topic.id == DocumentTopic.topic_id)
            .where(DocumentTopic.model_version_id == mv.id, DocumentTopic.document_id.in_(list(doc_bucket)))
        ).all()
        if doc_bucket
        else []
    )
    num: dict[tuple, int] = Counter((doc_bucket[r.document_id], r.key) for r in rows)
    series = defaultdict(list)
    for (b, key), n in sorted(num.items()):
        d = denom[b]
        suppressed = d < MIN_CELL
        series[key].append(
            {
                "period": b,
                "documents": d,
                "mentions": None if suppressed else n,
                "share": None if suppressed else round(n / d, 4),
                "suppressed": suppressed,
            }
        )
    coverage = {
        "documents": len(docs),
        "duplicates_excluded": db.scalar(
            select(func.count())
            .select_from(Document)
            .where(
                Document.country_code == country,
                Document.published_at >= start,
                Document.published_at < end,
                Document.duplicate_of_id.is_not(None),
            )
        ),
        "sources": len({d.source_id for d in docs}),
        "languages": dict(Counter(d.language for d in docs)),
        "geo_confidence": dict(Counter(d.geo_confidence for d in docs)),
        "periods": dict(sorted(denom.items())),
    }
    return {
        "model_version": mv.version,
        "taxonomy_version": TAXONOMY_VERSION,
        "series": dict(series),
        "coverage": coverage,
        "labels": {k: v["label"] for k, v in TOPICS.items()},
        "min_cell": MIN_CELL,
    }
