"""
Combined analysis over a batch of predicted articles.

Mirrors the aggregation performed in ``inferencija_svi_clanci.ipynb``:

* per-topic mention rate and stance shares,
* ``net_stance = (n_for - n_against) / n_mentioned``,
* an overall final-label distribution,
* a heatmap of articles x topics (final label per cell), and
* an ensemble model-comparison (LogReg vs BERTić agreement).
"""
from __future__ import annotations

from typing import Dict, List

from .constants import FOUR_CLASSES, STANCE_CLASSES, TOPIC_NAMES, TOPICS


def build_summary(articles_results: List[dict], article_meta: List[dict],
                  method: str) -> dict:
    n = len(articles_results)

    per_topic = {}
    for topic in TOPICS:
        n_mentioned = 0
        counts = {"for": 0, "against": 0, "neutral": 0}
        for res in articles_results:
            tr = res["topics"][topic]
            if tr["mentioned"] and tr["stance"] is not None:
                n_mentioned += 1
                counts[tr["stance"]] += 1

        def share(x):
            return (x / n_mentioned) if n_mentioned else 0.0

        net_stance = ((counts["for"] - counts["against"]) / n_mentioned
                      if n_mentioned else 0.0)

        per_topic[topic] = {
            "name": TOPIC_NAMES[topic],
            "n_articles": n,
            "n_mentioned": n_mentioned,
            "mention_rate": (n_mentioned / n) if n else 0.0,
            "n_for": counts["for"],
            "n_against": counts["against"],
            "n_neutral": counts["neutral"],
            "share_for": share(counts["for"]),
            "share_against": share(counts["against"]),
            "share_neutral": share(counts["neutral"]),
            "net_stance": net_stance,
        }

    # Overall final-label distribution (counted across all article x topic cells)
    distribution = {cls: 0 for cls in FOUR_CLASSES}
    for res in articles_results:
        for topic in TOPICS:
            distribution[res["topics"][topic]["final"]] += 1

    # Heatmap: rows = articles, cols = topics, cell = final label + confidence
    heatmap = {
        "topics": [{"key": t, "name": TOPIC_NAMES[t]} for t in TOPICS],
        "rows": [],
    }
    for res, meta in zip(articles_results, article_meta):
        cells = []
        for topic in TOPICS:
            tr = res["topics"][topic]
            cells.append({
                "topic": topic,
                "final": tr["final"],
                "confidence": tr["confidence"],
                "p_mentioned": tr["p_mentioned"],
            })
        heatmap["rows"].append({
            "title": meta.get("title") or "(untitled)",
            "source": meta.get("source") or "manual",
            "cells": cells,
        })

    summary = {
        "n_articles": n,
        "method": method,
        "per_topic": per_topic,
        "distribution": distribution,
        "heatmap": heatmap,
    }

    if method == "ensemble":
        summary["model_comparison"] = _model_comparison(articles_results)

    return summary


def _argmax_label(probs: Dict[str, float], classes) -> str:
    return max(classes, key=lambda c: probs.get(c, -1.0))


def _model_comparison(articles_results: List[dict]) -> dict:
    """Compare LogReg vs BERTić decisions across all article x topic cells."""
    total = 0
    agree = 0
    disagreements = []

    for a_i, res in enumerate(articles_results):
        for topic in TOPICS:
            tr = res["topics"][topic]
            pm = tr.get("per_model")
            if not pm:
                continue
            lr, bt = pm.get("LogReg"), pm.get("BERTić")
            if not lr or not bt or not lr["binary"] or not bt["binary"]:
                continue

            lr_bin = _argmax_label(lr["binary"], ["not_mentioned", "mentioned"])
            bt_bin = _argmax_label(bt["binary"], ["not_mentioned", "mentioned"])

            lr_final = _resolve_final(lr_bin, lr["stance"])
            bt_final = _resolve_final(bt_bin, bt["stance"])

            total += 1
            if lr_final == bt_final:
                agree += 1
            else:
                disagreements.append({
                    "article_index": a_i,
                    "topic": topic,
                    "topic_name": TOPIC_NAMES[topic],
                    "logreg": lr_final,
                    "bertic": bt_final,
                })

    return {
        "total_cells": total,
        "agreements": agree,
        "agreement_rate": (agree / total) if total else 0.0,
        "n_disagreements": len(disagreements),
        "disagreements": disagreements[:50],
    }


def _resolve_final(binary_label: str, stance_probs) -> str:
    if binary_label != "mentioned" or not stance_probs:
        return "not_mentioned"
    return _argmax_label(stance_probs, STANCE_CLASSES)
