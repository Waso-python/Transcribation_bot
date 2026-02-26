import shutil
import subprocess
import wave
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status

from app.core.config import Settings

SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".ogg", ".m4a"}


class MediaProcessingError(RuntimeError):
    pass


async def save_upload(file: UploadFile, destination_dir: Path, max_size_bytes: int) -> Path:
    destination_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type. Allowed: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )

    file_path = destination_dir / f"{uuid4()}{ext}"
    size = 0
    with file_path.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > max_size_bytes:
                out.close()
                file_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="Uploaded file exceeds configured size limit",
                )
            out.write(chunk)
    return file_path


def normalize_audio(input_path: Path, settings: Settings) -> Path:
    if not settings.transcode_enabled:
        if input_path.suffix.lower() == ".wav":
            return input_path
        raise MediaProcessingError("Transcoding is disabled. Only WAV input is accepted.")

    output_path = input_path.with_suffix(".normalized.wav")
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(input_path),
        "-ac",
        "1",
        "-ar",
        "16000",
        str(output_path),
    ]
    _run_subprocess(cmd, "Audio transcoding failed")
    return output_path


def audio_duration_seconds(path: Path) -> float:
    if path.suffix.lower() == ".wav":
        with wave.open(str(path), "rb") as wf:
            frames = wf.getnframes()
            frame_rate = wf.getframerate()
            return frames / float(frame_rate)

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    output = _run_subprocess(cmd, "Audio probing failed")
    return float(output.strip())


def cleanup_file(path: Path) -> None:
    if path.exists():
        path.unlink(missing_ok=True)


def cleanup_dir(path: Path) -> None:
    if path.exists() and path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


def _run_subprocess(cmd: list[str], error_message: str) -> str:
    try:
        completed = subprocess.run(cmd, capture_output=True, check=True, text=True)
        return completed.stdout
    except FileNotFoundError as exc:
        raise MediaProcessingError(f"Required binary not found: {cmd[0]}") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise MediaProcessingError(f"{error_message}: {stderr}") from exc
