"""Small trained statistical model; parsing and money arithmetic are separate."""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

CATEGORIES = {
    "drive": "Motion & drive",
    "fastener": "Fasteners",
    "electronics": "Electronics",
    "fabrication": "Fabrication",
    "consumables": "Shop supplies",
}


def words(text: str) -> list[str]:
    return re.findall(r"[a-z][a-z0-9]+", text.casefold())


def features(text: str) -> Counter:
    tokens = words(text)
    return Counter(tokens + [a + " " + b for a, b in zip(tokens, tokens[1:])])


class PartsClassifier:
    """Multinomial Naive Bayes, fitted at startup on original labelled examples."""

    def __init__(self, dataset: Path | None = None):
        source = dataset or Path(__file__).with_name("training_data.json")
        self.dataset = json.loads(source.read_text(encoding="utf-8"))
        self.counts = {category: Counter() for category in CATEGORIES}
        self.documents = {}
        for category, examples in self.dataset["training"].items():
            self.documents[category] = len(examples)
            for description in examples:
                self.counts[category].update(features(description))
        self.vocabulary = set().union(*(set(c) for c in self.counts.values()))
        self.known_words = {w for w in self.vocabulary if " " not in w}
        self.totals = {c: sum(count.values()) for c, count in self.counts.items()}
        self.alpha = 0.6

    def predict(self, description: str) -> dict:
        fs = features(description)
        known = {f: n for f, n in fs.items() if f in self.vocabulary}
        count = sum(self.documents.values())
        score = {}
        for category in CATEGORIES:
            denominator = self.totals[category] + self.alpha * len(self.vocabulary)
            score[category] = math.log(self.documents[category] / count)
            score[category] += sum(n * math.log((self.counts[category][f] + self.alpha) / denominator) for f, n in known.items())
        ranked = sorted(score, key=lambda c: (-score[c], c))
        top, runner_up = ranked[:2]
        shifted = {c: math.exp(v - score[top]) for c, v in score.items()}
        confidence = shifted[top] / sum(shifted.values())
        tokens = words(description)
        coverage = sum(w in self.known_words for w in tokens) / max(1, len(tokens))
        evidence = []
        for f, n in known.items():
            gain = n * (math.log((self.counts[top][f] + self.alpha) / (self.totals[top] + self.alpha * len(self.vocabulary))) - math.log((self.counts[runner_up][f] + self.alpha) / (self.totals[runner_up] + self.alpha * len(self.vocabulary))))
            if gain > 0:
                evidence.append((gain, f))
        evidence.sort(reverse=True)
        uncertain = confidence < 0.72 or coverage < 0.4 or not known
        return {
            "category": top if known else "consumables",
            "confidence": round(confidence, 4),
            "coverage": round(coverage, 4),
            "needs_review": uncertain,
            "evidence_terms": [f for _, f in evidence[:3]],
            "alternatives": [{"category": c, "score": round(shifted[c] / sum(shifted.values()), 4)} for c in ranked[:3]],
            "model": "local-multinomial-naive-bayes-v1",
        }

    def information(self) -> dict:
        holdout = self.dataset["holdout"]
        correct = sum(self.predict(x["description"])["category"] == x["category"] for x in holdout)
        return {
            "name": "Local parts classifier",
            "algorithm": "Multinomial Naive Bayes with word and word-pair features",
            "training_examples": sum(self.documents.values()),
            "holdout_examples": len(holdout),
            "holdout_correct": correct,
            "holdout_accuracy": round(correct / len(holdout), 3),
            "dataset": "Original synthetic descriptions with authored category labels, five categories",
            "limitations": "Small English-domain model. Scores are not calibrated probabilities. Novel or ambiguous items require review; cost owners always require confirmation.",
            "external_model_calls": 0,
        }
