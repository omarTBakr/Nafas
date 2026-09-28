"""Build step: fetch the pinned weights into their model dirs. `python -m tts.download`."""

from huggingface_hub import snapshot_download

from tts.config import Settings


def main() -> None:
    settings = Settings()
    pinned = [(settings.model_id, settings.model_revision, settings.model_dir)]
    if settings.use_egyptian_model:
        pinned.append((settings.egyptian_model_id, settings.egyptian_model_revision, settings.egyptian_model_dir))
    # each model speaks through the same codec, found in its own dir's audio_tokenizer/
    for directory in [d for _, _, d in pinned]:
        pinned.append((settings.audio_tokenizer_id, settings.audio_tokenizer_revision, f"{directory}/audio_tokenizer"))
    for model_id, revision, directory in pinned:
        snapshot_download(
            model_id, revision=revision, local_dir=directory, allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model"]
        )
        print(f"{model_id}@{revision} -> {directory}")


if __name__ == "__main__":
    main()
