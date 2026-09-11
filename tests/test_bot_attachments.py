"""Тесты хелперов вложений MAX-бота (main.py), без сети."""
import main


def test_attachment_extension():
    assert main.attachment_extension("photo.PNG") == "png"
    assert main.attachment_extension("noext") == ""


def test_attachment_url_from_payload():
    attachment = {"type": "file", "payload": {"url": "https://fu.oneme.ru/x"}}
    assert main.attachment_url(attachment) == "https://fu.oneme.ru/x"


def test_attachment_url_missing():
    assert main.attachment_url({"type": "file", "payload": {}}) is None


def test_attachment_filename_from_field():
    attachment = {"type": "file", "filename": "doc.pdf", "payload": {"url": "https://x/y"}}
    assert main.attachment_filename(attachment, "https://x/y", 1) == "doc.pdf"


def test_attachment_filename_synthesized_for_image():
    attachment = {"type": "image", "payload": {"url": "https://iu.oneme.ru/abc"}}
    assert main.attachment_filename(attachment, "https://iu.oneme.ru/abc", 2) == "attachment_2.jpg"


def test_attachment_filename_from_url_path():
    url = "https://fu.oneme.ru/files/report.pdf"
    attachment = {"type": "file", "payload": {"url": url}}
    assert main.attachment_filename(attachment, url, 1) == "report.pdf"


def test_extract_incoming_attachments():
    update = {
        "message": {
            "body": {
                "text": "",
                "attachments": [
                    {"type": "file", "payload": {"url": "https://x/1"}, "filename": "a.pdf"},
                    "not-a-dict",
                ],
            }
        }
    }
    result = main.extract_incoming_attachments(update)
    assert len(result) == 1
    assert result[0]["filename"] == "a.pdf"


def test_extract_incoming_attachments_none():
    assert main.extract_incoming_attachments({"message": {"body": {"text": "hi"}}}) == []
