"""Azure Speech TTS 클라이언트 — Dragon HD Omni (Ava) 음성으로 MP3 생성."""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Alexa <audio> 태그 요구사항에 맞는 출력 포맷
# MP3, 48kbps, 24kHz, mono (MPEG version 2)
_OUTPUT_FORMAT = "audio-24khz-48kbitrate-mono-mp3"
_VOICE_NAME = "en-US-Ava:DragonHDOmniLatestNeural"

# MP3 저장 디렉토리
OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# 오래된 파일 삭제 기준 (초) — 10분
_MAX_AGE_SECONDS = 600


def _cleanup_old_files() -> None:
    """오래된 MP3 파일 정리."""
    now = time.time()
    for f in OUTPUT_DIR.glob("*.mp3"):
        if now - f.stat().st_mtime > _MAX_AGE_SECONDS:
            try:
                f.unlink()
            except OSError:
                pass


async def synthesize_speech(text: str) -> str | None:
    """텍스트를 Azure TTS로 변환하여 MP3 파일로 저장하고 파일명을 반환한다.

    Returns:
        MP3 파일명 (예: "abc123.mp3") 또는 실패 시 None.
    """
    key = settings.azure_speech_key
    region = settings.azure_speech_region
    if not key or not region:
        logger.warning("Azure Speech 키 또는 리전이 설정되지 않음")
        return None

    _cleanup_old_files()

    # 파일명: 텍스트 해시 기반 (동일 텍스트 → 캐시 활용)
    text_hash = hashlib.md5(text.encode()).hexdigest()[:12]
    filename = f"{text_hash}.mp3"
    filepath = OUTPUT_DIR / filename

    # 캐시 히트: 이미 존재하면 바로 반환
    if filepath.exists():
        logger.info("TTS 캐시 히트: %s", filename)
        return filename

    # SSML 생성 — lang 힌트로 한국어 발음 최적화
    ssml = (
        '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        'xmlns:mstts="http://www.w3.org/2001/mstts" xml:lang="en-US">'
        f'<voice name="{_VOICE_NAME}">'
        f'<lang xml:lang="ko-KR">{_escape_xml(text)}</lang>'
        '</voice></speak>'
    )

    url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
    headers = {
        "Ocp-Apim-Subscription-Key": key,
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": _OUTPUT_FORMAT,
        "User-Agent": "BusWatchHome",
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, content=ssml, headers=headers)
            resp.raise_for_status()

        filepath.write_bytes(resp.content)
        logger.info("TTS 생성 완료: %s (%d bytes)", filename, len(resp.content))
        return filename

    except Exception:
        logger.exception("Azure TTS 호출 실패")
        return None


def _escape_xml(text: str) -> str:
    """SSML용 XML 이스케이프."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
