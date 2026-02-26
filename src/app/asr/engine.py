from dataclasses import dataclass


@dataclass(slots=True)
class Segment:
    start: float
    end: float
    text: str


@dataclass(slots=True)
class AsrResult:
    text: str
    segments: list[Segment]
    language: str = "ru"


class AsrEngine:
    async def warmup(self) -> None:
        return None

    async def transcribe(self, wav_path: str, punctuation: bool = True) -> AsrResult:
        raise NotImplementedError
