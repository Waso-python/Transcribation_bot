import asyncio
import logging
import re
import shutil
import wave
from pathlib import Path
from typing import Any

from app.asr.engine import AsrEngine, AsrResult, Segment

logger = logging.getLogger(__name__)


class FasterWhisperEngine(AsrEngine):
    def __init__(
        self,
        model_name: str,
        language: str = "ru",
        device: str | None = None,
        compute_type: str = "float16",
        beam_size: int = 5,
        vad_filter: bool = True,
        task: str = "transcribe",
        download_root: str | None = None,
        force_mock: bool = False,
    ) -> None:
        self.model_name = model_name
        self.language = language
        self.device = device
        self.compute_type = compute_type
        self.beam_size = beam_size
        self.vad_filter = vad_filter
        self.task = task
        self.download_root = download_root
        self.force_mock = force_mock

        self._ready = False
        self._provider = "mock"
        self._model: Any | None = None

    async def warmup(self) -> None:
        if self.force_mock:
            self._provider = "mock"
            self._ready = True
            logger.warning("ASR mock mode is enabled explicitly.")
            return
        try:
            self._model = await asyncio.to_thread(self._load_model)
            self._provider = "faster_whisper"
            logger.info("Faster-Whisper model loaded successfully: %s", self.model_name)
        except Exception as exc:
            logger.exception("Failed to load Faster-Whisper. Falling back to mock mode: %s", exc)
            self._model = None
            self._provider = "mock"
        self._ready = True

    async def transcribe(self, wav_path: str, punctuation: bool = True) -> AsrResult:
        if not self._ready:
            await self.warmup()

        duration = _wav_duration_seconds(wav_path)
        if self._provider == "faster_whisper" and self._model is not None:
            return await asyncio.to_thread(self._transcribe_with_model, wav_path)
        return self._mock_transcribe(wav_path, duration, punctuation)

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def provider(self) -> str:
        return self._provider

    def _load_model(self):
        from faster_whisper import WhisperModel  # type: ignore

        selected_device = self.device or _default_device()
        kwargs: dict[str, Any] = {
            "device": selected_device,
            "compute_type": self.compute_type,
        }
        if self.download_root:
            kwargs["download_root"] = self.download_root

        try:
            return WhisperModel(self.model_name, **kwargs)
        except Exception as exc:
            converted = self._maybe_convert_hf_model(exc, selected_device)
            if converted is not None:
                return WhisperModel(str(converted), **kwargs)
            if selected_device == "cuda":
                logger.warning(
                    "Faster-Whisper CUDA load failed (%s). Falling back to CPU int8.", exc
                )
                kwargs["device"] = "cpu"
                kwargs["compute_type"] = "int8"
                try:
                    return WhisperModel(self.model_name, **kwargs)
                except Exception as cpu_exc:
                    converted = self._maybe_convert_hf_model(cpu_exc, "cpu")
                    if converted is not None:
                        return WhisperModel(str(converted), **kwargs)
                    raise
            raise

    def _transcribe_with_model(self, wav_path: str) -> AsrResult:
        assert self._model is not None
        segments_iter, info = self._model.transcribe(
            wav_path,
            language=self.language,
            task=self.task,
            beam_size=self.beam_size,
            vad_filter=self.vad_filter,
            condition_on_previous_text=True,
        )
        segments: list[Segment] = []
        for seg in segments_iter:
            text = (seg.text or "").strip()
            if not text:
                continue
            segments.append(
                Segment(
                    start=float(seg.start or 0.0),
                    end=float(seg.end or 0.0),
                    text=text,
                )
            )
        merged_text = " ".join(item.text for item in segments).strip()
        language = getattr(info, "language", None) or self.language
        return AsrResult(text=merged_text, segments=segments, language=language)

    def _mock_transcribe(self, wav_path: str, duration: float, punctuation: bool) -> AsrResult:
        text = f"Mock transcription ({Path(wav_path).name}, {duration:.2f}s)"
        if punctuation and not text.endswith("."):
            text += "."
        segments = [Segment(start=0.0, end=max(duration, 0.1), text=text)]
        return AsrResult(text=text, segments=segments, language=self.language)

    def _maybe_convert_hf_model(self, exc: Exception, device: str) -> Path | None:
        message = str(exc)
        if "Unable to open file 'model.bin'" not in message:
            return None
        if Path(self.model_name).exists():
            return None
        if "/" not in self.model_name:
            return None

        target_dir = self._converted_model_dir()
        model_bin = target_dir / "model.bin"
        if model_bin.exists():
            self._ensure_whisper_aux_files(target_dir)
            logger.info("Using existing converted CTranslate2 model: %s", target_dir)
            return target_dir
        if target_dir.exists():
            logger.warning("Removing incomplete converted model directory: %s", target_dir)
            shutil.rmtree(target_dir, ignore_errors=True)

        logger.warning(
            "Model '%s' is not a CTranslate2 checkpoint. Converting to CTranslate2 format...",
            self.model_name,
        )
        target_dir.mkdir(parents=True, exist_ok=True)
        try:
            from ctranslate2.converters import TransformersConverter  # type: ignore
        except Exception as import_exc:
            raise RuntimeError(
                "Failed to convert HF model to CTranslate2. Install converter deps: "
                "python -m pip install transformers sentencepiece"
            ) from import_exc

        quantization = "int8"
        if device == "cuda":
            quantization = "float16" if self.compute_type == "float16" else "int8_float16"
        converter = TransformersConverter(self.model_name)
        try:
            converter.convert(
                output_dir=str(target_dir),
                quantization=quantization,
                copy_files=["tokenizer.json", "tokenizer_config.json", "vocab.json", "merges.txt"],
                force=True,
            )
        except TypeError:
            try:
                converter.convert(
                    output_dir=str(target_dir),
                    quantization=quantization,
                    force=True,
                )
            except TypeError:
                converter.convert(
                    output_dir=str(target_dir),
                    quantization=quantization,
                )
        self._ensure_whisper_aux_files(target_dir)
        logger.info("CTranslate2 conversion completed: %s", target_dir)
        return target_dir

    def _converted_model_dir(self) -> Path:
        root = Path(self.download_root) if self.download_root else Path.home() / ".cache" / "ctranslate2"
        safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", self.model_name)
        return root / f"{safe_name}-{self.compute_type}"

    def _ensure_whisper_aux_files(self, target_dir: Path) -> None:
        if "/" not in self.model_name:
            return
        needed = [
            "preprocessor_config.json",
            "tokenizer.json",
            "tokenizer_config.json",
            "vocab.json",
            "merges.txt",
            "added_tokens.json",
            "special_tokens_map.json",
        ]
        missing = [name for name in needed if not (target_dir / name).exists()]
        if not missing:
            return
        try:
            from huggingface_hub import snapshot_download  # type: ignore
        except Exception as exc:
            logger.warning("Cannot import huggingface_hub to sync aux files: %s", exc)
            return

        source_dir = Path(snapshot_download(repo_id=self.model_name))
        copied = 0
        for name in missing:
            src = source_dir / name
            dst = target_dir / name
            if src.exists() and not dst.exists():
                shutil.copy2(src, dst)
                copied += 1
        if copied:
            logger.info("Copied %d auxiliary model files into %s", copied, target_dir)


def _default_device() -> str:
    try:
        import torch  # type: ignore

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _wav_duration_seconds(path: str) -> float:
    with wave.open(path, "rb") as wf:
        frames = wf.getnframes()
        frame_rate = wf.getframerate()
        return frames / float(frame_rate)
