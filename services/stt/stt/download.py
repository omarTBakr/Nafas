"""Build step: fetch the pinned weights into model_dir. `python -m stt.download`."""

from huggingface_hub import snapshot_download

from stt.config import Settings


def main() -> None:
    settings = Settings()
    snapshot_download(
        settings.model_id,
        revision=settings.model_revision,
        local_dir=settings.model_dir,
        # only what inference loads: no training state, no sample audio
        allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model"],
    )
    print(f"{settings.model_id}@{settings.model_revision} -> {settings.model_dir}")


if __name__ == "__main__":
    main()
