from dataclasses import dataclass
from typing import Protocol

from dialect_router.config import Settings


@dataclass
class Prediction:
    label: str
    score: float
    # every label's probability, so a caller can see a close second
    scores: dict[str, float]


class Classifier(Protocol):
    device: str
    labels: list[str]

    def classify(self, texts: list[str]) -> list[Prediction]: ...


class TransformersClassifier:
    """
    The Hugging Face model, loaded once from the weights baked into the image.

    torch and transformers are imported here rather than at module level, so
    the API and its tests run without the multi-gigabyte model runtime.
    """

    def __init__(self, settings: Settings):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self._torch = torch
        self._max_length = settings.max_length

        if settings.device == "auto":
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = settings.device

        source = settings.model_dir if _has_weights(settings.model_dir) else settings.model_id
        revision = None if source == settings.model_dir else settings.model_revision

        self._tokenizer = AutoTokenizer.from_pretrained(source, revision=revision)
        self._model = AutoModelForSequenceClassification.from_pretrained(source, revision=revision)
        self._model.to(self.device).eval()

        id2label = self._model.config.id2label
        self.labels = [id2label[i] for i in range(len(id2label))]

    def classify(self, texts: list[str]) -> list[Prediction]:
        torch = self._torch
        inputs = self._tokenizer(texts, return_tensors="pt", truncation=True, max_length=self._max_length, padding=True).to(
            self.device
        )

        with torch.inference_mode():
            probabilities = torch.softmax(self._model(**inputs).logits, dim=-1).cpu()

        predictions = []
        for row in probabilities.tolist():
            scores = dict(zip(self.labels, row, strict=True))
            best = max(scores, key=scores.get)
            predictions.append(Prediction(label=best, score=scores[best], scores=scores))

        return predictions


def _has_weights(model_dir: str) -> bool:
    from pathlib import Path

    return (Path(model_dir) / "config.json").is_file()
