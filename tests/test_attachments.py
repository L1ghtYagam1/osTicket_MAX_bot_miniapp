"""Тесты валидатора вложений заявки (backend/services.py)."""
import base64

import pytest

from backend import services


def _attachment(filename: str, data: bytes = b"hello", content_type: str = "") -> dict:
    return {
        "filename": filename,
        "content_type": content_type,
        "data_base64": base64.b64encode(data).decode("ascii"),
    }


def test_empty_returns_empty():
    assert services.validate_and_prepare_attachments(None) == []
    assert services.validate_and_prepare_attachments([]) == []


def test_valid_attachment_prepared():
    prepared = services.validate_and_prepare_attachments([_attachment("report.pdf")])
    assert len(prepared) == 1
    assert prepared[0]["name"] == "report.pdf"
    assert prepared[0]["mime"] == "application/pdf"
    assert prepared[0]["data_base64"]


def test_explicit_content_type_preserved():
    prepared = services.validate_and_prepare_attachments(
        [_attachment("a.png", content_type="image/png")]
    )
    assert prepared[0]["mime"] == "image/png"


def test_too_many_rejected(monkeypatch):
    monkeypatch.setattr(services.settings, "attachment_max_count", 1)
    with pytest.raises(ValueError):
        services.validate_and_prepare_attachments([_attachment("a.png"), _attachment("b.png")])


def test_disallowed_extension_rejected():
    with pytest.raises(ValueError):
        services.validate_and_prepare_attachments([_attachment("evil.exe")])


def test_too_large_rejected(monkeypatch):
    monkeypatch.setattr(services.settings, "attachment_max_file_size_mb", 1)
    big = b"x" * (2 * 1024 * 1024)
    with pytest.raises(ValueError):
        services.validate_and_prepare_attachments([_attachment("big.txt", data=big)])


def test_invalid_base64_rejected():
    with pytest.raises(ValueError):
        services.validate_and_prepare_attachments(
            [{"filename": "a.png", "content_type": "", "data_base64": "!!!not-base64!!!"}]
        )


def test_missing_filename_rejected():
    with pytest.raises(ValueError):
        services.validate_and_prepare_attachments(
            [{"filename": "", "content_type": "", "data_base64": base64.b64encode(b"x").decode()}]
        )
