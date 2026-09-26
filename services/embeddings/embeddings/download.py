"""Build step: fetch the weights into model_dir. `python -m embeddings.download`."""

from huggingface_hub import snapshot_download

from embeddings.config import Settings


def main() -> None:
    settings = Settings()
    snapshot_download(
        settings.model_id,
        revision=settings.model_revision,
        local_dir=settings.model_dir,
        allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "1_Pooling/*", "sentencepiece.bpe.model"],
    )
    print(f"{settings.model_id}@{settings.model_revision} -> {settings.model_dir}")


if __name__ == "__main__":
    main()
