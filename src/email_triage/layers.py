"""The three scoring layers.

Layer 1 (structural) and Layer 2 (rules) are deterministic, dependency-free, and
always available. Layer 3 (embeddings) is optional: if the ONNX model is absent
the engine renormalizes the remaining weights and caps confidence, rather than
failing. See pipeline SP-1.1-18/19/20.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .config import CompiledConcern, CompiledPattern, Config
from .textprep import PreparedText


# --------------------------------------------------------------------------
# Layer 1: structural
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PatternHit:
    pattern: str
    text: str
    span: tuple[int, int]
    segment: str

    def to_dict(self) -> dict:
        return {
            "pattern": self.pattern,
            "text": self.text,
            "span": [self.span[0], self.span[1]],
            "segment": self.segment,
        }


def find_pattern_hits(
    prepared: PreparedText, patterns: dict[str, CompiledPattern]
) -> tuple[PatternHit, ...]:
    """Run every library pattern over every segment. Offsets are absolute
    against prepared.full so the UI can highlight them."""
    hits: list[PatternHit] = []
    for seg in prepared.segments:
        for name, pat in patterns.items():
            for raw, (s, e) in pat.finditer(seg.text):
                hits.append(
                    PatternHit(
                        pattern=name,
                        text=raw,
                        span=(seg.offset + s, seg.offset + e),
                        segment=seg.kind,
                    )
                )
    return tuple(hits)


def structural_score(
    concern: CompiledConcern, hits: tuple[PatternHit, ...]
) -> tuple[float, bool]:
    """Fraction of the concern's field patterns that appear anywhere, plus
    whether the structural gate is satisfied."""
    present = {h.pattern for h in hits}
    wanted = {f.pattern.name for f in concern.fields if f.pattern is not None}
    score = len(wanted & present) / len(wanted) if wanted else 0.0
    gate_ok = True
    if concern.gate_patterns:
        gate_ok = any(p in present for p in concern.gate_patterns)
    return score, gate_ok


# --------------------------------------------------------------------------
# Layer 2: keyword and phrase rules
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RuleScore:
    score: float
    hits: tuple[str, ...]
    decisive: tuple[str, ...]


def rule_score(concern: CompiledConcern, prepared: PreparedText, cfg: Config) -> RuleScore:
    """Weighted keyword scoring over the newest message, squashed to 0..1.

    Segment weights mean a hit in the subject counts nearly as much as the body,
    while a hit in quoted history counts far less.
    """
    total = 0.0
    hits: list[str] = []
    for seg in prepared.segments:
        weight = cfg.segment_weights.get(seg.kind, 0.5)
        low = seg.text.lower()
        for rule in concern.positive:
            n = len(rule.matcher.findall(low)) if rule.matcher else low.count(rule.phrase)
            if n:
                # Repeats add sub-linearly; saying "type of bill" five times is
                # not five times the evidence.
                total += rule.weight * weight * (1.0 + math.log(n))
                hits.append(rule.phrase)
        for rule in concern.negative:
            n = len(rule.matcher.findall(low)) if rule.matcher else low.count(rule.phrase)
            if n:
                total -= rule.weight * weight * (1.0 + math.log(n))

    decisive: list[str] = []
    classify_low = prepared.classify_text.lower()
    for terms in concern.decisive:
        if all(t in classify_low for t in terms):
            decisive.append(" + ".join(terms))

    # tanh squash: saturating, monotonic, and never negative.
    score = math.tanh(max(total, 0.0) / 4.0)
    return RuleScore(score=score, hits=tuple(dict.fromkeys(hits)), decisive=tuple(decisive))


# --------------------------------------------------------------------------
# Layer 3: embeddings (optional)
# --------------------------------------------------------------------------

MODEL_DIRNAME = "model"
MODEL_FILENAME = "model_quint8_avx2.onnx"
TOKENIZER_FILENAME = "tokenizer.json"
MAX_TOKENS = 128


class EmbeddingLayer:
    """MiniLM sentence embeddings via ONNX Runtime on CPU.

    Prototypes are embedded with the same session that scores queries, which is
    the condition that keeps int8 quantization safe (pipeline SP-1.1-16).
    """

    def __init__(self, model_dir, temperature: float = 0.05) -> None:
        from pathlib import Path

        import numpy as np  # noqa: F401  (import here so absence is a clean failure)
        import onnxruntime as ort
        from tokenizers import Tokenizer

        model_dir = Path(model_dir)
        model_path = model_dir / MODEL_FILENAME
        tok_path = model_dir / TOKENIZER_FILENAME
        if not model_path.exists() or not tok_path.exists():
            raise FileNotFoundError(f"model files not found under {model_dir}")

        ort.disable_telemetry_events()
        ort.set_default_logger_severity(3)

        so = ort.SessionOptions()
        # Weak target CPUs, and Outlook may be running alongside.
        import os

        so.intra_op_num_threads = max(1, min(2, (os.cpu_count() or 2) // 2))
        so.inter_op_num_threads = 1
        so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        # Without this the thread pool spin-waits between calls and pins a core
        # at 100% while idle -- very visible on a 2-core machine.
        so.add_session_config_entry("session.intra_op.allow_spinning", "0")
        so.add_session_config_entry("session.inter_op.allow_spinning", "0")
        so.add_session_config_entry("session.set_denormal_as_zero", "1")
        so.enable_profiling = False

        self._sess = ort.InferenceSession(
            str(model_path), sess_options=so, providers=["CPUExecutionProvider"]
        )
        self._input_names = {i.name for i in self._sess.get_inputs()}

        self._tok = Tokenizer.from_file(str(tok_path))
        self._tok.enable_truncation(max_length=MAX_TOKENS)
        self._tok.enable_padding(length=MAX_TOKENS)

        self.temperature = temperature
        self._prototypes: dict[str, "object"] = {}

    def embed(self, texts: list[str]):
        """Masked mean pooling + L2 normalization.

        The ONNX export emits last_hidden_state, not a sentence embedding. This
        pooling step is the part that is easy to get subtly wrong.
        """
        import numpy as np

        if not texts:
            return np.zeros((0, 384), dtype=np.float32)

        out = []
        for i in range(0, len(texts), 8):
            chunk = texts[i : i + 8]
            encs = self._tok.encode_batch(chunk)
            ids = np.array([e.ids for e in encs], dtype=np.int64)
            mask = np.array([e.attention_mask for e in encs], dtype=np.int64)
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self._input_names:
                feed["token_type_ids"] = np.array([e.type_ids for e in encs], dtype=np.int64)
            hidden = self._sess.run(None, feed)[0]
            m = mask[..., None].astype(np.float32)
            summed = (hidden * m).sum(axis=1)
            counts = np.clip(m.sum(axis=1), 1e-9, None)
            emb = summed / counts
            norms = np.clip(np.linalg.norm(emb, axis=1, keepdims=True), 1e-12, None)
            out.append((emb / norms).astype(np.float32))
        return np.concatenate(out, axis=0)

    def fit_prototypes(self, cfg: Config) -> None:
        """Embed each concern's prototypes + examples, and the background class."""
        for concern in cfg.enabled_concerns:
            texts = list(concern.prototypes) + list(concern.examples)
            if texts:
                self._prototypes[concern.id] = self.embed(texts)
        if cfg.background_prototypes:
            self._prototypes[cfg.background_id] = self.embed(list(cfg.background_prototypes))

    def similarities(self, text: str) -> dict[str, float]:
        """Max cosine similarity of the query against each class's prototypes."""
        import numpy as np

        if not self._prototypes:
            return {}
        q = self.embed([text])[0]
        return {
            cid: float(np.max(mat @ q)) for cid, mat in self._prototypes.items()
        }

    def probabilities(self, text: str) -> dict[str, float]:
        """Softmax over max-similarities. Temperature is configurable because
        cosine values for a small encoder sit in a narrow band."""
        import numpy as np

        sims = self.similarities(text)
        if not sims:
            return {}
        keys = list(sims)
        vals = np.array([sims[k] for k in keys], dtype=np.float32)
        scaled = (vals - vals.max()) / max(self.temperature, 1e-6)
        exp = np.exp(scaled)
        probs = exp / exp.sum()
        return {k: float(p) for k, p in zip(keys, probs)}


def try_load_embeddings(cfg: Config, model_dir=None) -> EmbeddingLayer | None:
    """Return a fitted EmbeddingLayer, or None if it cannot be used.

    Absence is a supported state, not an error: the engine falls back to
    rules + structural with a capped confidence.
    """
    from pathlib import Path

    from .config import RESOURCES

    model_dir = Path(model_dir) if model_dir else RESOURCES / MODEL_DIRNAME
    try:
        layer = EmbeddingLayer(model_dir, temperature=cfg.embedding_temperature)
        layer.fit_prototypes(cfg)
        return layer
    except (ImportError, FileNotFoundError, OSError):
        return None
