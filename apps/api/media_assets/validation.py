import hashlib
import json
import os
import subprocess
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import filetype
from django.conf import settings

from media_assets.models import MediaAsset
from media_assets.storage import ObjectStorage, checksum_base64


class MediaValidationError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ValidatedMedia:
    duration_seconds: Decimal | None
    width: int | None
    height: int | None


ALLOWED_EXTENSIONS: dict[str, set[str]] = {
    MediaAsset.Kind.IMAGE: {".jpg", ".jpeg", ".png", ".webp"},
    MediaAsset.Kind.AUDIO: {".mp3", ".m4a", ".aac", ".ogg"},
    MediaAsset.Kind.VIDEO: {".mp4"},
}
ALLOWED_MAGIC: dict[str, set[str]] = {
    MediaAsset.Kind.IMAGE: {"image/jpeg", "image/png", "image/webp"},
    MediaAsset.Kind.AUDIO: {"audio/mpeg", "audio/mp4", "audio/aac", "audio/ogg"},
    MediaAsset.Kind.VIDEO: {"video/mp4"},
}


def validate_asset(asset: MediaAsset, storage: ObjectStorage) -> ValidatedMedia:
    head = storage.head(key=asset.object_key)
    if head.get("ContentLength") != asset.size_bytes:
        raise MediaValidationError("Uploaded size does not match the declared size.")
    provider_checksum = head.get("ChecksumSHA256")
    if provider_checksum and provider_checksum != checksum_base64(asset.sha256):
        raise MediaValidationError("Uploaded checksum does not match the declared checksum.")
    if Path(asset.original_name).suffix.lower() not in ALLOWED_EXTENSIONS[asset.kind]:
        raise MediaValidationError("File extension is not allowed for this media type.")

    with _materialize(storage.read(key=asset.object_key)) as file_path:
        detected = filetype.guess(file_path)
        if detected is None or detected.mime not in ALLOWED_MAGIC[asset.kind]:
            raise MediaValidationError("File content does not match the declared media type.")
        if _sha256(file_path) != asset.sha256:
            raise MediaValidationError("Uploaded checksum does not match the declared checksum.")
        if asset.kind == MediaAsset.Kind.IMAGE:
            return _probe_image(file_path)
        return _probe_media(file_path, asset.kind)


class _materialize:
    def __init__(self, chunks: Iterator[bytes]) -> None:
        self.chunks = chunks
        self.path: str | None = None

    def __enter__(self) -> str:
        with tempfile.NamedTemporaryFile(delete=False) as file:
            self.path = file.name
            for chunk in self.chunks:
                file.write(chunk)
        return self.path

    def __exit__(self, *args: object) -> None:
        if self.path:
            os.unlink(self.path)


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _probe_image(path: str) -> ValidatedMedia:
    payload = _ffprobe(path)
    stream = _first_stream(payload, "video")
    width = stream.get("width")
    height = stream.get("height")
    if not isinstance(width, int) or not isinstance(height, int) or width < 1 or height < 1:
        raise MediaValidationError("Image dimensions are invalid.")
    return ValidatedMedia(duration_seconds=None, width=width, height=height)


def _probe_media(path: str, kind: str) -> ValidatedMedia:
    payload = _ffprobe(path)
    format_data = payload.get("format", {})
    duration = format_data.get("duration")
    try:
        duration_decimal = Decimal(str(duration))
    except Exception as error:
        raise MediaValidationError("Media duration is invalid.") from error
    if duration_decimal <= 0 or duration_decimal > settings.MEDIA_MAX_DURATION_SECONDS:
        raise MediaValidationError("Media duration is outside the allowed range.")

    audio = _first_stream(payload, "audio")
    if audio.get("codec_name") != "aac" and kind == MediaAsset.Kind.VIDEO:
        raise MediaValidationError("Video must use AAC audio.")
    if kind == MediaAsset.Kind.AUDIO and audio.get("codec_name") not in {"aac", "mp3", "vorbis"}:
        raise MediaValidationError("Audio codec is not allowed.")
    if kind == MediaAsset.Kind.VIDEO:
        video = _first_stream(payload, "video")
        if video.get("codec_name") != "h264":
            raise MediaValidationError("Video must use H.264.")
        width = video.get("width")
        height = video.get("height")
        if not isinstance(width, int) or not isinstance(height, int) or width < 1 or height < 1:
            raise MediaValidationError("Video dimensions are invalid.")
        return ValidatedMedia(duration_seconds=duration_decimal, width=width, height=height)
    return ValidatedMedia(duration_seconds=duration_decimal, width=None, height=None)


def _ffprobe(path: str) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [
                settings.MEDIA_FFPROBE_PATH,
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=codec_type,codec_name,width,height",
                "-of",
                "json",
                path,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=settings.MEDIA_FFPROBE_TIMEOUT_SECONDS,
        )
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict):
            raise MediaValidationError("Media metadata could not be read.")
        return cast(dict[str, Any], payload)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        raise MediaValidationError("Media metadata could not be read.") from error


def _first_stream(payload: dict[str, Any], codec_type: str) -> dict[str, Any]:
    streams = payload.get("streams")
    if not isinstance(streams, list):
        raise MediaValidationError("Required media stream is missing.")
    for stream in streams:
        if isinstance(stream, dict) and stream.get("codec_type") == codec_type:
            return cast(dict[str, Any], stream)
    raise MediaValidationError("Required media stream is missing.")
