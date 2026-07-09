"""
Model loading and two-stage prediction.

The loading and inference logic is ported directly from
``evaluation_logreg_bertic_ensemble.ipynb`` /
``inferencija_svi_clanci.ipynb`` so that predictions made by the web
application are identical to the notebooks:

* LogReg reads the article **content** (``SADRZAJ``) only.
* BERTić reads **title + ". " + content** (``TEXT_BERT``).
* Binary stage decides mentioned / not_mentioned.
* Stance stage runs only when the article is *mentioned*.
* The ensemble is a weighted soft-vote of the two probability vectors.

Heavy dependencies (torch / transformers / sklearn / joblib / numpy) are
imported lazily, and only when the model artefacts are actually present. If
they are missing the caller falls back to :mod:`predictor.ml.demo`.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Dict, List, Optional

from .constants import BINARY_CLASSES, STANCE_CLASSES, TOPICS


# ---------------------------------------------------------------------------
# Artefact discovery (ported from the notebooks)
# ---------------------------------------------------------------------------
def _is_hf_model_dir(path: Path) -> bool:
    path = Path(path)
    weights_exist = any(
        (path / name).exists()
        for name in ["model.safetensors", "pytorch_model.bin"]
    )
    return path.is_dir() and (path / "config.json").exists() and weights_exist


def _find_file_recursively(root: Path, filename: str) -> Optional[Path]:
    matches = list(Path(root).rglob(filename))
    return matches[0] if matches else None


def _find_bert_model_dir(root: Path, topic: str, task: str) -> Optional[Path]:
    root = Path(root)
    if task == "binary":
        candidate_names = [topic, f"bertic_{topic}_final"]
    else:
        candidate_names = [topic, f"bertic_stance_{topic}_final"]

    for name in candidate_names:
        candidate = root / name
        if _is_hf_model_dir(candidate):
            return candidate
    for name in candidate_names:
        for candidate in root.rglob(name):
            if _is_hf_model_dir(candidate):
                return candidate
    for config_path in root.rglob("config.json"):
        candidate = config_path.parent
        if topic in str(candidate) and _is_hf_model_dir(candidate):
            return candidate
    return None


def artefacts_available(cfg: dict) -> bool:
    """Return True when at least the LogReg binary artefacts can be located.

    LogReg alone is enough to serve the ``logreg`` method; BERTić availability
    is checked per-method at prediction time.
    """
    root = Path(cfg["LOGREG_BINARY_SOURCE"])
    if not root.exists():
        return False
    for topic in TOPICS:
        if _find_file_recursively(root, f"{topic}__logreg_binary.joblib") is None:
            return False
    return True


# ---------------------------------------------------------------------------
# Class alignment (ported 1:1)
# ---------------------------------------------------------------------------
def _normalize_label(label: str) -> str:
    text = str(label).strip()
    aliases = {"not mentioned": "not_mentioned", "not-mentioned": "not_mentioned"}
    return aliases.get(text.lower(), text.lower())


def _align_probability_columns(probabilities, source_classes, target_classes,
                               fallback_label_order=None):
    source = [_normalize_label(x) for x in source_classes]
    target = [_normalize_label(x) for x in target_classes]

    if all(label in source for label in target):
        positions = [source.index(label) for label in target]
        return probabilities[:, positions]

    generic = all(label.startswith("label_") for label in source)
    if generic and fallback_label_order is not None:
        fallback = [_normalize_label(x) for x in fallback_label_order]
        mapping = dict(zip(source, fallback))
        mapped_source = [mapping[x] for x in source]
        if all(label in mapped_source for label in target):
            positions = [mapped_source.index(label) for label in target]
            return probabilities[:, positions]

    raise ValueError(
        f"Cannot align classes. source={source_classes}, target={target_classes}"
    )


class PredictionEngine:
    """Loads the trained models once and serves two-stage predictions."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self._loaded = False
        self._lock = threading.Lock()

        self.logreg_binary: Dict[str, object] = {}
        self.logreg_stance: Dict[str, object] = {}
        self.bert_binary: Dict[str, dict] = {}
        self.bert_stance: Dict[str, dict] = {}
        self.has_logreg = False
        self.has_bert = False

    # -- loading ----------------------------------------------------------
    def load(self) -> None:
        with self._lock:
            if self._loaded:
                return

            import joblib  # noqa: local import, heavy dependency

            cfg = self.cfg
            lr_bin_root = Path(cfg["LOGREG_BINARY_SOURCE"])
            lr_stc_root = Path(cfg["LOGREG_STANCE_SOURCE"])
            bert_bin_root = Path(cfg["BERT_BINARY_SOURCE"])
            bert_stc_root = Path(cfg["BERT_STANCE_SOURCE"])

            # LogReg
            try:
                for topic in TOPICS:
                    b = _find_file_recursively(
                        lr_bin_root, f"{topic}__logreg_binary.joblib")
                    s = _find_file_recursively(
                        lr_stc_root, f"{topic}__logreg_stance.joblib")
                    if b is None or s is None:
                        raise FileNotFoundError(topic)
                    self.logreg_binary[topic] = joblib.load(b)
                    self.logreg_stance[topic] = joblib.load(s)
                self.has_logreg = True
            except Exception:
                self.has_logreg = False

            # BERTić (optional)
            try:
                from transformers import (  # noqa: local heavy import
                    AutoModelForSequenceClassification,
                    AutoTokenizer,
                )
                import torch

                device = torch.device(
                    "cuda" if torch.cuda.is_available() else "cpu")
                self._device = device

                for topic in TOPICS:
                    b_dir = _find_bert_model_dir(bert_bin_root, topic, "binary")
                    s_dir = _find_bert_model_dir(bert_stc_root, topic, "stance")
                    if b_dir is None or s_dir is None:
                        raise FileNotFoundError(topic)
                    self.bert_binary[topic] = {
                        "tokenizer": AutoTokenizer.from_pretrained(b_dir),
                        "model": AutoModelForSequenceClassification
                        .from_pretrained(b_dir).to(device).eval(),
                    }
                    self.bert_stance[topic] = {
                        "tokenizer": AutoTokenizer.from_pretrained(s_dir),
                        "model": AutoModelForSequenceClassification
                        .from_pretrained(s_dir).to(device).eval(),
                    }
                self.has_bert = True
            except Exception:
                self.has_bert = False

            self._loaded = True

    # -- low-level probability helpers -----------------------------------
    def _sklearn_probs(self, model, texts, target_classes):
        probs = model.predict_proba(list(texts))
        return _align_probability_columns(probs, model.classes_, target_classes)

    def _bert_probs(self, bundle, texts, target_classes):
        import numpy as np
        import torch

        model = bundle["model"]
        tokenizer = bundle["tokenizer"]
        batch_size = self.cfg["BERT_BATCH_SIZE"]
        max_length = self.cfg["MAX_LENGTH"]

        texts = list(map(str, texts))
        chunks = []
        with torch.inference_mode():
            for start in range(0, len(texts), batch_size):
                batch = texts[start:start + batch_size]
                enc = tokenizer(batch, truncation=True, padding=True,
                                max_length=max_length, return_tensors="pt")
                enc = {k: v.to(self._device) for k, v in enc.items()}
                logits = model(**enc).logits
                chunks.append(torch.softmax(logits, dim=1).cpu().numpy())

        probabilities = (np.vstack(chunks) if chunks
                         else np.empty((0, len(target_classes))))
        id2label = model.config.id2label
        source_classes = [
            id2label.get(i, id2label.get(str(i), f"LABEL_{i}"))
            for i in range(probabilities.shape[1])
        ]
        return _align_probability_columns(
            probabilities, source_classes, target_classes,
            fallback_label_order=target_classes)

    def _weighted_soft_vote(self, lr, bert):
        w_lr = self.cfg["LOGREG_WEIGHT"]
        w_bt = self.cfg["BERT_WEIGHT"]
        probs = w_lr * lr + w_bt * bert
        return probs / probs.sum(axis=1, keepdims=True)

    # -- public API -------------------------------------------------------
    def method_available(self, method: str) -> bool:
        if method == "logreg":
            return self.has_logreg
        if method == "bertic":
            return self.has_bert
        if method == "ensemble":
            return self.has_logreg and self.has_bert
        return False

    def predict(self, articles: List[dict], method: str) -> List[dict]:
        """Run the two-stage pipeline over every topic for each article.

        ``articles`` is a list of ``{"title": str, "content": str}`` dicts.
        Returns one result dict per article (see aggregate.py for the shape).
        """
        import numpy as np

        self.load()

        logreg_texts = [str(a.get("content", "")) for a in articles]
        bert_texts = [
            f'{str(a.get("title", ""))}. {str(a.get("content", ""))}'
            for a in articles
        ]

        want_lr = method in {"logreg", "ensemble"}
        want_bt = method in {"bertic", "ensemble"}

        results = [
            {"topics": {}, "method": method} for _ in articles
        ]

        for topic in TOPICS:
            # -------------------- binary stage (all articles) -----------
            per_model_bin = {}
            if want_lr:
                per_model_bin["LogReg"] = self._sklearn_probs(
                    self.logreg_binary[topic], logreg_texts, BINARY_CLASSES)
            if want_bt:
                per_model_bin["BERTić"] = self._bert_probs(
                    self.bert_binary[topic], bert_texts, BINARY_CLASSES)

            if method == "ensemble":
                bin_probs = self._weighted_soft_vote(
                    per_model_bin["LogReg"], per_model_bin["BERTić"])
            elif method == "logreg":
                bin_probs = per_model_bin["LogReg"]
            else:
                bin_probs = per_model_bin["BERTić"]

            mentioned_idx = BINARY_CLASSES.index("mentioned")
            p_mentioned = bin_probs[:, mentioned_idx]
            is_mentioned = np.argmax(bin_probs, axis=1) == mentioned_idx

            # -------------------- stance stage (mentioned subset) -------
            m_idx = np.where(is_mentioned)[0]
            stance_full = np.full((len(articles), len(STANCE_CLASSES)), np.nan)
            per_model_stc = {}
            if m_idx.size > 0:
                sub_lr = [logreg_texts[i] for i in m_idx]
                sub_bt = [bert_texts[i] for i in m_idx]
                if want_lr:
                    per_model_stc["LogReg"] = self._sklearn_probs(
                        self.logreg_stance[topic], sub_lr, STANCE_CLASSES)
                if want_bt:
                    per_model_stc["BERTić"] = self._bert_probs(
                        self.bert_stance[topic], sub_bt, STANCE_CLASSES)

                if method == "ensemble":
                    s_probs = self._weighted_soft_vote(
                        per_model_stc["LogReg"], per_model_stc["BERTić"])
                elif method == "logreg":
                    s_probs = per_model_stc["LogReg"]
                else:
                    s_probs = per_model_stc["BERTić"]
                stance_full[m_idx] = s_probs

            # -------------------- assemble per article ------------------
            for row, art_result in enumerate(results):
                art_result["topics"][topic] = self._assemble_topic(
                    row, m_idx, method,
                    bin_probs, p_mentioned, is_mentioned,
                    stance_full, per_model_bin, per_model_stc,
                )

        for art_result in results:
            _finalise_article(art_result)
        return results

    def _assemble_topic(self, row, m_idx, method, bin_probs, p_mentioned,
                        is_mentioned, stance_full, per_model_bin, per_model_stc):
        import numpy as np

        mentioned = bool(is_mentioned[row])
        binary_probs = {
            cls: float(bin_probs[row, i]) for i, cls in enumerate(BINARY_CLASSES)
        }
        topic_res = {
            "mentioned": mentioned,
            "p_mentioned": float(p_mentioned[row]),
            "binary_probs": binary_probs,
            "stance": None,
            "stance_probs": None,
        }

        if mentioned and not np.isnan(stance_full[row]).any():
            sp = stance_full[row]
            stance_probs = {
                cls: float(sp[i]) for i, cls in enumerate(STANCE_CLASSES)
            }
            stance = STANCE_CLASSES[int(np.argmax(sp))]
            topic_res["stance"] = stance
            topic_res["stance_probs"] = stance_probs

        if method == "ensemble":
            topic_res["per_model"] = self._per_model_block(
                row, m_idx, per_model_bin, per_model_stc)

        return topic_res

    def _per_model_block(self, row, m_idx, per_model_bin, per_model_stc):
        import numpy as np

        block = {}
        # position of this row within the mentioned subset (if present)
        sub_pos = None
        where = np.where(m_idx == row)[0]
        if where.size:
            sub_pos = int(where[0])

        for name in ("LogReg", "BERTić"):
            entry = {"binary": None, "stance": None}
            if name in per_model_bin:
                bp = per_model_bin[name][row]
                entry["binary"] = {
                    cls: float(bp[i]) for i, cls in enumerate(BINARY_CLASSES)
                }
            if name in per_model_stc and sub_pos is not None:
                sp = per_model_stc[name][sub_pos]
                entry["stance"] = {
                    cls: float(sp[i]) for i, cls in enumerate(STANCE_CLASSES)
                }
            block[name] = entry
        return block


# ---------------------------------------------------------------------------
# Shared post-processing (used by both the real engine and the demo engine)
# ---------------------------------------------------------------------------
def _finalise_article(art_result: dict) -> None:
    """Derive per-topic final labels/confidence and the article headline."""
    best = None
    for topic, tr in art_result["topics"].items():
        if tr["mentioned"] and tr["stance"] is not None:
            final = tr["stance"]
            confidence = tr["stance_probs"][final]
        else:
            final = "not_mentioned"
            confidence = tr["binary_probs"]["not_mentioned"]
        tr["final"] = final
        tr["confidence"] = confidence

        # combined two-stage 4-class distribution (for visualisation)
        p_ment = tr["p_mentioned"]
        four = {"not_mentioned": 1.0 - p_ment}
        if tr["stance_probs"] is not None:
            for cls, val in tr["stance_probs"].items():
                four[cls] = p_ment * val
        else:
            for cls in ("against", "neutral", "for"):
                four[cls] = p_ment / 3.0
        tr["four_probs"] = four

        if tr["mentioned"]:
            score = tr["p_mentioned"] * confidence
            if best is None or score > best["score"]:
                best = {"topic": topic, "final": final,
                        "confidence": confidence, "score": score}

    if best is None:
        art_result["headline"] = {
            "topic": None, "final": "not_mentioned", "confidence": None,
        }
    else:
        art_result["headline"] = {
            "topic": best["topic"], "final": best["final"],
            "confidence": best["confidence"],
        }


# ---------------------------------------------------------------------------
# Process-wide singleton
# ---------------------------------------------------------------------------
_ENGINE: Optional[PredictionEngine] = None
_ENGINE_LOCK = threading.Lock()


def get_engine(cfg: dict) -> PredictionEngine:
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            _ENGINE = PredictionEngine(cfg)
        return _ENGINE
