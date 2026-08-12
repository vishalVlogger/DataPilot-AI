import re
from pathlib import Path
from uuid import uuid4

from app.core.errors import AppError
from app.services.object_storage import get_object_storage


ALLOWED_TYPES: dict[str, set[str]] = {
    ".png": {"image/png"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".webp": {"image/webp"},
    ".pdf": {"application/pdf"},
    ".txt": {"text/plain", "application/octet-stream"},
    ".log": {"text/plain", "application/octet-stream"},
}


def validate_feedback_attachment(filename: str, content_type: str | None, content: bytes, max_bytes: int) -> tuple[str, str]:
    original = Path((filename or "attachment").replace("\\", "/")).name[:255]
    extension = Path(original).suffix.casefold()
    normalized_type = (content_type or "application/octet-stream").split(";", 1)[0].strip().casefold()
    if extension not in ALLOWED_TYPES or normalized_type not in ALLOWED_TYPES[extension]:
        raise AppError("This attachment type is not supported. Use PNG, JPG, WebP, PDF, TXT, or LOG.", "FEEDBACK_ATTACHMENT_TYPE_INVALID", 400)
    if not content or len(content) > max_bytes:
        raise AppError("The attachment is empty or exceeds the configured size limit.", "FEEDBACK_ATTACHMENT_SIZE_INVALID", 413)
    signatures = {
        ".png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        ".jpg": content.startswith(b"\xff\xd8\xff"),
        ".jpeg": content.startswith(b"\xff\xd8\xff"),
        ".webp": len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP",
        ".pdf": content.startswith(b"%PDF-"),
    }
    if extension in signatures and not signatures[extension]:
        raise AppError("The attachment content does not match its file type.", "FEEDBACK_ATTACHMENT_CONTENT_INVALID", 400)
    if extension in {".txt", ".log"}:
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AppError("Text attachments must be UTF-8 text.", "FEEDBACK_ATTACHMENT_CONTENT_INVALID", 400) from exc
        if b"\x00" in content:
            raise AppError("Binary files cannot be uploaded as text attachments.", "FEEDBACK_ATTACHMENT_CONTENT_INVALID", 400)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(original).stem).strip(".-")[:120] or "attachment"
    return original, f"{stem}{extension}"


class FeedbackAttachmentStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve(); self.objects = get_object_storage()

    def save(self, workspace_id: str, feedback_id: str, safe_filename: str, content: bytes) -> tuple[str, str, str]:
        for value in (workspace_id, feedback_id):
            if not value or any(character not in "0123456789abcdef-" for character in value.casefold()):
                raise AppError("Feedback attachment target is invalid.", "FEEDBACK_ATTACHMENT_TARGET_INVALID", 400)
        attachment_id = str(uuid4())
        key = f"workspaces/{workspace_id}/feedback/{feedback_id}/{attachment_id}/{safe_filename}"
        self.objects.put(key, content); return attachment_id, key, key

    def resolve(self, storage_key: str) -> Path:
        from app.services.object_storage import LocalObjectStorage
        if not isinstance(self.objects, LocalObjectStorage): raise AppError("Direct paths are unavailable for object storage.", "STORAGE_PATH_UNAVAILABLE", 409)
        return self.objects.path(storage_key)

    def read(self, storage_key: str) -> bytes: return self.objects.get(storage_key)

    def remove(self, key: str | Path) -> None: self.objects.delete(str(key).replace("\\", "/"))
