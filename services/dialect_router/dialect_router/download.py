"""Build step: fetch the pinned weights into model_dir. `python -m dialect_router.download`."""

from huggingface_hub import snapshot_download

from dialect_router.config import Settings


def main() -> None:
    settings = Settings()
    snapshot_download(
        settings.model_id,
        revision=settings.model_revision,
        local_dir=settings.model_dir,
        # training_args.bin is a pickle the service never needs
        allow_patterns=["*.json", "*.safetensors", "vocab.txt"],
    )
    print(f"{settings.model_id}@{settings.model_revision} -> {settings.model_dir}")


if __name__ == "__main__":
    main()
