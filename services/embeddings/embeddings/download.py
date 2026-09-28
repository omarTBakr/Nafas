"""Build step: fetch the weights into model_dir. `python -m embeddings.download`."""

from pathlib import Path

from huggingface_hub import snapshot_download

from embeddings.config import Settings

# What sentence-transformers loads, at the top level of the repo only: bge-m3
# ships its weights as pytorch_model.bin (it has no model.safetensors), and
# its onnx/, colbert and sparse heads are not used here.
ALLOW = [
    "config.json",
    "config_sentence_transformers.json",
    "modules.json",
    "sentence_bert_config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "sentencepiece.bpe.model",
    "model.safetensors",
    "pytorch_model.bin",
    "1_Pooling/*",
]
WEIGHTS = ("model.safetensors", "pytorch_model.bin")


def main() -> None:
    settings = Settings()
    snapshot_download(settings.model_id, revision=settings.model_revision, local_dir=settings.model_dir, allow_patterns=ALLOW)

    # an image without weights builds fine and dies on start; fail the build instead
    model_dir = Path(settings.model_dir)
    if not any((model_dir / name).is_file() for name in WEIGHTS):
        raise SystemExit(f"no weights ({' or '.join(WEIGHTS)}) downloaded into {model_dir}")

    print(f"{settings.model_id}@{settings.model_revision} -> {settings.model_dir}")


if __name__ == "__main__":
    main()
