"""
High-level entry point used by the views.

Decides between the trained :class:`PredictionEngine` and the deterministic
:mod:`demo` predictor, and attaches the combined analysis for a batch.
"""
from __future__ import annotations

from typing import List

from django.conf import settings

from . import demo
from .aggregate import build_summary
from .constants import METHOD_NAMES, METHODS
from .engine import artefacts_available, get_engine


def engine_status() -> dict:
    """Report whether trained models are available and which methods work."""
    cfg = settings.ML_CONFIG
    if cfg.get("FORCE_DEMO"):
        return {
            "mode": "demo",
            "reason": "FORCE_DEMO is enabled.",
            "available_methods": list(METHODS),
            "method_names": METHOD_NAMES,
        }

    if not artefacts_available(cfg):
        return {
            "mode": "demo",
            "reason": "Trained model files were not found under MODELS_ROOT.",
            "available_methods": list(METHODS),
            "method_names": METHOD_NAMES,
        }

    engine = get_engine(cfg)
    engine.load()
    available = [m for m in METHODS if engine.method_available(m)]
    return {
        "mode": "models",
        "reason": "Trained models loaded.",
        "available_methods": available,
        "method_names": METHOD_NAMES,
    }


def predict_articles(articles: List[dict], method: str) -> dict:
    """Run predictions + combined analysis.

    ``articles`` -> list of ``{"title", "content", "source"}``.
    Returns ``{"results": [...], "summary": {...}, "mode": "models"|"demo"}``.
    """
    if method not in METHODS:
        raise ValueError(f"Unknown method: {method!r}")

    cfg = settings.ML_CONFIG
    use_demo = cfg.get("FORCE_DEMO") or not artefacts_available(cfg)

    mode = "demo"
    if not use_demo:
        engine = get_engine(cfg)
        engine.load()
        if engine.method_available(method):
            results = engine.predict(articles, method)
            mode = "models"
        else:
            results = demo.predict(articles, method)
    else:
        results = demo.predict(articles, method)

    # attach article metadata to each result and to the summary
    meta = [
        {"title": a.get("title", ""), "source": a.get("source", "manual")}
        for a in articles
    ]
    for res, m, art in zip(results, meta, articles):
        res["title"] = m["title"]
        res["source"] = m["source"]
        content = art.get("content", "") or ""
        res["content_preview"] = content[:280]

    summary = build_summary(results, meta, method)
    return {"results": results, "summary": summary, "mode": mode}
