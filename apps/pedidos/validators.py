from django.core.files.uploadedfile import InMemoryUploadedFile
from core.exceptions import FileSizeExceededError, InvalidFileTypeError

# 20 MB por arquivo
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024

ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain",
    "text/csv",
    "application/zip",
}


def validate_pedido_id(pedido: str) -> str:
    """Valida e normaliza o número do pedido."""
    pedido = pedido.strip()
    if not pedido:
        raise ValueError("O campo 'pedido' não pode ser vazio.")
    if len(pedido) > 100:
        raise ValueError("O campo 'pedido' deve ter no máximo 100 caracteres.")
    # Permite apenas alfanuméricos, hífen e underscore
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
    if not all(c in allowed for c in pedido):
        raise ValueError("O campo 'pedido' contém caracteres inválidos. Use apenas letras, números, hífen e underscore.")
    return pedido


def validate_file(file: InMemoryUploadedFile) -> None:
    """Valida tamanho e tipo de um arquivo."""
    if file.size > MAX_FILE_SIZE_BYTES:
        raise FileSizeExceededError(
            f"O arquivo '{file.name}' excede o limite de {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB."
        )

    content_type = getattr(file, "content_type", "")
    if content_type and content_type not in ALLOWED_MIME_TYPES:
        raise InvalidFileTypeError(
            f"Tipo de arquivo não permitido: '{content_type}'. "
            f"Tipos aceitos: {', '.join(sorted(ALLOWED_MIME_TYPES))}"
        )


def validate_files(files: list) -> None:
    """Valida uma lista de arquivos."""
    if not files:
        raise ValueError("Nenhum arquivo enviado.")
    if len(files) > 20:
        raise ValueError("Máximo de 20 arquivos por upload.")
    for file in files:
        validate_file(file)
