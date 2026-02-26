from app.asr.engine import AsrEngine
from app.asr.faster_whisper_engine import FasterWhisperEngine
from app.asr.gigaam_engine import GigaAMEngine
from app.core.config import Settings


def build_asr_engine(settings: Settings) -> AsrEngine:
    if settings.asr_backend == "faster_whisper":
        return FasterWhisperEngine(
            model_name=settings.faster_whisper_model,
            language=settings.language_default,
            device=settings.asr_device,
            compute_type=settings.faster_whisper_compute_type,
            beam_size=settings.faster_whisper_beam_size,
            vad_filter=settings.faster_whisper_vad_filter,
            task=settings.faster_whisper_task,
            download_root=settings.faster_whisper_download_root,
            force_mock=settings.asr_force_mock,
        )

    return GigaAMEngine(
        model_name=settings.model_name,
        language=settings.language_default,
        force_mock=settings.asr_force_mock,
        device=settings.asr_device,
        use_flash=settings.gigaam_use_flash,
        download_root=settings.gigaam_download_root,
        hf_token=settings.hf_token,
    )
