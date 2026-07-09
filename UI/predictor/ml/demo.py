"""
Deterministic, dependency-free fallback predictor.

This is **not** a trained model. It produces the same result structure as
:class:`predictor.ml.engine.PredictionEngine` using a transparent keyword and
stance-lexicon heuristic, so the interface is fully demonstrable when the real
model artefacts are not installed. Results are deterministic for a given text
(seeded by a hash of the text) which keeps the demo stable and repeatable.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Dict, List

from .constants import BINARY_CLASSES, STANCE_CLASSES, TOPICS
from .engine import _finalise_article


# Topic keyword lexicons (lower-cased, accent-tolerant matching).
TOPIC_KEYWORDS = {
    "euroatlantske_integracije": [
        "nato", "eu", "evropsk", "europsk", "evroatlant", "euroatlant",
        "integracij", "brisel", "clanstvo", "pristupanj", "zapad",
        "evropska unija", "sjeverноatlant", "sjevernoatlant",
    ],
    "negiranje_genocida": [
        "genocid", "srebrenic", "potocar", "potočar", "negiranj", "poric",
        "ratni zlocin", "zrtv", "žrtv", "masakr", "11. juli", "mladic",
        "karadzic", "karadžić", "haski", "haški",
    ],
    "gradjanska_vs_konstitutivni": [
        "konstitutivn", "gradjansk", "građansk", "narod", "entitet",
        "ustav", "ustavn", "reprezentativn", "kolektivn prav", "dejton",
        "federacij", "republika srpska", "diskriminacij",
    ],
    "izborna_reforma": [
        "izborn", "izbor", "reform", "izborni zakon", "cik", "biracki",
        "birački", "glasanj", "mandat", "kandidat", "izborna jedinica",
        "izmjena zakona",
    ],
}

# Stance lexicons.
POSITIVE_WORDS = [
    "podrska", "podrška", "podrzava", "podržava", "napredak", "prilika",
    "pozitiv", "korist", "saradnj", "dogovor", "reform", "pomirenj",
    "priznanj", "istina", "pravd", "buducnost", "budućnost", "razvoj",
    "stabilnost", "za ",
]
NEGATIVE_WORDS = [
    "protiv", "prijetnj", "prijetnja", "opasnost", "nazadovanj", "kriz",
    "sukob", "blokad", "negira", "porice", "laz", "laž", "napad",
    "odbacuj", "kritik", "osud", "prevar", "nepravd", "prijetiti",
]


def _norm(text: str) -> str:
    return (text or "").lower()


def _count_hits(text: str, words: List[str]) -> int:
    return sum(text.count(w) for w in words)


def _seed(text: str) -> float:
    h = hashlib.md5(text.encode("utf-8")).hexdigest()
    return (int(h[:8], 16) % 1000) / 1000.0  # 0.0 .. 0.999


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _softmax3(a: float, b: float, c: float) -> Dict[str, float]:
    m = max(a, b, c)
    ea, eb, ec = math.exp(a - m), math.exp(b - m), math.exp(c - m)
    s = ea + eb + ec
    return {"against": ea / s, "neutral": eb / s, "for": ec / s}


def predict(articles: List[dict], method: str) -> List[dict]:
    results = []
    for art in articles:
        title = _norm(art.get("title", ""))
        content = _norm(art.get("content", ""))
        text = f"{title} . {content}"
        # length in tokens, used to scale keyword density
        length = max(len(re.findall(r"\w+", text)), 1)
        jitter = _seed(text)

        art_result = {"topics": {}, "method": method}

        for topic in TOPICS:
            hits = _count_hits(text, TOPIC_KEYWORDS[topic])
            density = hits / math.sqrt(length)
            # probability the topic is mentioned
            p_ment = _sigmoid(4.0 * density - 1.4 + 0.4 * (jitter - 0.5))
            p_ment = min(max(p_ment, 0.02), 0.98)
            mentioned = p_ment >= 0.5

            binary_probs = {
                "not_mentioned": 1.0 - p_ment,
                "mentioned": p_ment,
            }

            topic_res = {
                "mentioned": mentioned,
                "p_mentioned": p_ment,
                "binary_probs": binary_probs,
                "stance": None,
                "stance_probs": None,
            }

            if mentioned:
                pos = _count_hits(text, POSITIVE_WORDS)
                neg = _count_hits(text, NEGATIVE_WORDS)
                against = 1.2 * neg + 0.6 * (jitter < 0.34)
                for_ = 1.2 * pos + 0.6 * (jitter > 0.66)
                neutral = 1.0 + 0.5 * (0.34 <= jitter <= 0.66)
                stance_probs = _softmax3(against, neutral, for_)
                stance = max(stance_probs, key=stance_probs.get)
                topic_res["stance"] = stance
                topic_res["stance_probs"] = stance_probs

            if method == "ensemble":
                topic_res["per_model"] = _demo_per_model(topic_res, jitter)

            art_result["topics"][topic] = topic_res

        _finalise_article(art_result)
        results.append(art_result)

    return results


def _demo_per_model(topic_res: dict, jitter: float) -> dict:
    """Fabricate two slightly-different per-model views for the ensemble demo."""
    def perturb(probs, delta):
        if probs is None:
            return None
        shifted = {k: max(v + delta * (0.5 - i / 2), 0.001)
                   for i, (k, v) in enumerate(probs.items())}
        s = sum(shifted.values())
        return {k: v / s for k, v in shifted.items()}

    d = (jitter - 0.5) * 0.16
    return {
        "LogReg": {
            "binary": perturb(topic_res["binary_probs"], d),
            "stance": perturb(topic_res["stance_probs"], d),
        },
        "BERTić": {
            "binary": perturb(topic_res["binary_probs"], -d),
            "stance": perturb(topic_res["stance_probs"], -d),
        },
    }
