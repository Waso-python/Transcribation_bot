import asyncio
import logging
import os
import tempfile
import wave
from pathlib import Path
from typing import Any

from app.asr.engine import AsrEngine, AsrResult, Segment

logger = logging.getLogger(__name__)

MODEL_ALIASES = {
    "GigaAM-v3-e2e": "v3_e2e_ctc",
    "gigaam-v3-e2e": "v3_e2e_ctc",
    "v3_e2e": "v3_e2e_ctc",
}


class GigaAMEngine(AsrEngine):
    def __init__(
        self,
        model_name: str,
        language: str = "ru",
        force_mock: bool = False,
        device: str | None = None,
        use_flash: bool = False,
        download_root: str | None = None,
        hf_token: str | None = None,
    ) -> None:
        self.model_name = _resolve_model_name(model_name)
        self.language = language
        self.force_mock = force_mock
        self.device = device
        self.use_flash = use_flash
        self.download_root = download_root
        self.hf_token = hf_token
        self._ready = False
        self._provider = "mock"
        self._model: Any | None = None

    async def warmup(self) -> None:
        if self.force_mock:
            self._provider = "mock"
            self._ready = True
            logger.warning("ASR mock mode is enabled explicitly.")
            return

        if self.hf_token:
            os.environ["HF_TOKEN"] = self.hf_token

        try:
            self._model = await asyncio.to_thread(self._load_gigaam_model)
            self._provider = "gigaam"
            logger.info("GigaAM model loaded successfully: %s", self.model_name)
        except Exception as exc:
            logger.exception("Failed to load GigaAM. Falling back to mock mode: %s", exc)
            self._model = None
            self._provider = "mock"
        self._ready = True

    async def transcribe(self, wav_path: str, punctuation: bool = True) -> AsrResult:
        if not self._ready:
            await self.warmup()

        duration = _wav_duration_seconds(wav_path)
        if self._provider == "gigaam" and self._model is not None:
            return await asyncio.to_thread(self._transcribe_with_gigaam, wav_path, duration)
        return self._mock_transcribe(wav_path, duration, punctuation)

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def provider(self) -> str:
        return self._provider

    def _load_gigaam_model(self):
        import gigaam  # type: ignore

        selected_device = self.device
        if not selected_device:
            try:
                import torch  # type: ignore

                selected_device = "cuda" if torch.cuda.is_available() else "cpu"
            except Exception:
                selected_device = "cpu"

        kwargs: dict[str, Any] = {
            "model_name": self.model_name,
            "device": selected_device,
            "use_flash": self.use_flash,
        }
        if self.download_root:
            kwargs["download_root"] = self.download_root
        try:
            return gigaam.load_model(**kwargs)
        except AssertionError as exc:
            message = str(exc)
            if "Torch not compiled with CUDA enabled" in message and selected_device == "cuda":
                logger.warning(
                    "CUDA build of torch is unavailable. Falling back to CPU for model loading."
                )
                kwargs["device"] = "cpu"
                return gigaam.load_model(**kwargs)
            raise

    def _transcribe_with_gigaam(self, wav_path: str, duration: float) -> AsrResult:
        assert self._model is not None
        if duration <= 25:
            text = str(self._model.transcribe(wav_path)).strip()
            segments = [Segment(start=0.0, end=max(duration, 0.1), text=text)]
            return AsrResult(text=text, segments=segments, language=self.language)

        try:
            utterances = self._model.transcribe_longform(wav_path)
        except ModuleNotFoundError as exc:
            if exc.name == "huggingface_hub":
                raise RuntimeError(
                    "Missing dependency 'huggingface_hub' required for longform transcription. "
                    "Install it with: python -m pip install huggingface-hub"
                ) from exc
            if exc.name in {"pyannote", "pyannote.audio"}:
                raise RuntimeError(
                    "Missing dependency 'pyannote.audio' required for longform transcription. "
                    "Install it with: python -m pip install pyannote.audio"
                ) from exc
            raise
        except Exception as exc:
            # Known Windows compatibility issue with huggingface_hub 1.x + pyannote local snapshot paths.
            if exc.__class__.__name__ == "HFValidationError":
                logger.warning(
                    "Longform VAD path failed (%s). Falling back to chunked short-form transcription.",
                    exc,
                )
                return self._transcribe_chunked_shortform(wav_path)
            raise
        segments: list[Segment] = []
        for item in utterances or []:
            boundaries = item.get("boundaries", (0.0, 0.0))
            start = float(boundaries[0]) if len(boundaries) > 0 else 0.0
            end = float(boundaries[1]) if len(boundaries) > 1 else start
            text = str(item.get("transcription", "")).strip()
            if text:
                segments.append(Segment(start=start, end=end, text=text))

        if not segments:
            return AsrResult(text="", segments=[], language=self.language)

        merged_text = " ".join(seg.text for seg in segments).strip()
        return AsrResult(text=merged_text, segments=segments, language=self.language)

    def _transcribe_chunked_shortform(self, wav_path: str, chunk_sec: float = 22.0) -> AsrResult:
        assert self._model is not None
        segments: list[Segment] = []
        with wave.open(wav_path, "rb") as src:
            channels = src.getnchannels()
            sample_width = src.getsampwidth()
            sample_rate = src.getframerate()
            total_frames = src.getnframes()
            frames_per_chunk = int(chunk_sec * sample_rate)
            if frames_per_chunk <= 0:
                frames_per_chunk = sample_rate

            with tempfile.TemporaryDirectory(prefix="gigaam_chunk_") as temp_dir:
                index = 0
                frame_cursor = 0
                while frame_cursor < total_frames:
                    src.setpos(frame_cursor)
                    chunk_frames = min(frames_per_chunk, total_frames - frame_cursor)
                    raw = src.readframes(chunk_frames)
                    chunk_path = Path(temp_dir) / f"chunk_{index}.wav"
                    with wave.open(str(chunk_path), "wb") as dst:
                        dst.setnchannels(channels)
                        dst.setsampwidth(sample_width)
                        dst.setframerate(sample_rate)
                        dst.writeframes(raw)

                    text = str(self._model.transcribe(str(chunk_path))).strip()
                    start = frame_cursor / sample_rate
                    end = (frame_cursor + chunk_frames) / sample_rate
                    if text:
                        segments.append(Segment(start=start, end=end, text=text))

                    frame_cursor += chunk_frames
                    index += 1

        merged_text = " ".join(seg.text for seg in segments).strip()
        return AsrResult(text=merged_text, segments=segments, language=self.language)

    def _mock_transcribe(self, wav_path: str, duration: float, punctuation: bool) -> AsrResult:
        text = f"Mock transcription ({Path(wav_path).name}, {duration:.2f}s)"
        if punctuation and not text.endswith("."):
            text += "."
        segments = [Segment(start=0.0, end=max(duration, 0.1), text=text)]
        return AsrResult(text=text, segments=segments, language=self.language)


def _wav_duration_seconds(path: str) -> float:
    with wave.open(path, "rb") as wf:
        frames = wf.getnframes()
        frame_rate = wf.getframerate()
        return frames / float(frame_rate)


def _resolve_model_name(name: str) -> str:
    resolved = MODEL_ALIASES.get(name, name)
    if resolved != name:
        logger.warning("MODEL_NAME '%s' is deprecated, using '%s' instead.", name, resolved)
    return resolved
