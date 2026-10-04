# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import default
from typing import BinaryIO


DEFAULT_MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_FORM_PARTS = 64
MAX_TEXT_FIELD_BYTES = 1024 * 1024


@dataclass(frozen=True)
class UploadedFile:
    filename: str
    content_type: str
    content: bytes


class MultipartForm:
    def __init__(
        self,
        *,
        fields: dict[str, list[str]] | None = None,
        files: dict[str, list[UploadedFile]] | None = None,
    ) -> None:
        self._fields = fields or {}
        self._files = files or {}

    def getfirst(self, name: str, default_value: str = "") -> str:
        values = self._fields.get(str(name), ())
        return values[0] if values else default_value

    def get_file(self, name: str) -> UploadedFile | None:
        values = self._files.get(str(name), ())
        return values[0] if values else None


def parse_multipart_form(
    stream: BinaryIO,
    *,
    content_type: str,
    content_length: int | str,
    max_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
) -> MultipartForm:
    media_type = str(content_type or "").strip()
    if not media_type.lower().startswith("multipart/form-data"):
        raise ValueError("request Content-Type must be multipart/form-data")

    try:
        length = int(content_length)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid Content-Length") from exc
    if length <= 0:
        raise ValueError("multipart request body is empty")
    if length > int(max_bytes):
        raise ValueError(f"upload exceeds the {int(max_bytes)} byte limit")

    body = stream.read(length)
    if len(body) != length:
        raise ValueError("multipart request body ended before Content-Length")

    envelope = (
        f"Content-Type: {media_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
        + body
    )
    message = BytesParser(policy=default).parsebytes(envelope)
    if not message.is_multipart():
        raise ValueError("invalid multipart/form-data body")

    fields: dict[str, list[str]] = {}
    files: dict[str, list[UploadedFile]] = {}
    parts = list(message.iter_parts())
    if len(parts) > MAX_FORM_PARTS:
        raise ValueError(f"multipart form contains more than {MAX_FORM_PARTS} parts")

    for part in parts:
        if part.get_content_disposition() != "form-data":
            continue
        name = str(part.get_param("name", header="content-disposition") or "").strip()
        if not name or len(name) > 128 or "\x00" in name:
            raise ValueError("multipart form contains an invalid field name")

        payload = part.get_payload(decode=True) or b""
        filename = part.get_filename()
        if filename is not None:
            safe_filename = _safe_filename(filename)
            files.setdefault(name, []).append(
                UploadedFile(
                    filename=safe_filename,
                    content_type=str(part.get_content_type() or "application/octet-stream"),
                    content=payload,
                )
            )
            continue

        if len(payload) > MAX_TEXT_FIELD_BYTES:
            raise ValueError(f"multipart text field {name!r} is too large")
        charset = part.get_content_charset() or "utf-8"
        try:
            value = payload.decode(charset)
        except (LookupError, UnicodeDecodeError) as exc:
            raise ValueError(f"multipart text field {name!r} has invalid encoding") from exc
        fields.setdefault(name, []).append(value)

    return MultipartForm(fields=fields, files=files)


def _safe_filename(filename: str) -> str:
    value = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not value or len(value) > 255 or "\x00" in value:
        raise ValueError("uploaded file has an invalid filename")
    return value
