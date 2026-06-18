import requests
import logging
from datetime import datetime
from django.core.files.uploadedfile import InMemoryUploadedFile
from core.exceptions import OneDriveError

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


# ─── Pasta ────────────────────────────────────────────────────────────────────

def ensure_folder(access_token: str, path: str) -> str:
    """
    Garante que o caminho de pastas exista no OneDrive.
    Cria recursivamente se necessário.
    Retorna o ID da pasta final.
    """
    parts = path.strip("/").split("/")
    parent_id = "root"

    for part in parts:
        parent_id = _ensure_single_folder(access_token, parent_id, part)

    return parent_id


def _ensure_single_folder(access_token: str, parent_id: str, folder_name: str) -> str:
    """Cria uma pasta dentro de parent_id se não existir. Retorna o ID da pasta."""
    # Lista todos os filhos e filtra localmente (Graph API não suporta filter em folder)
    url = f"{GRAPH_BASE}/me/drive/items/{parent_id}/children"
    params = {"$select": "id,name,folder", "$top": "999"}

    try:
        response = requests.get(url, headers=_headers(access_token), params=params, timeout=15)
        response.raise_for_status()
        all_items = response.json().get("value", [])
        # Filtra localmente: mesmo nome e é pasta
        items = [i for i in all_items if i.get("name") == folder_name and "folder" in i]
    except requests.RequestException as e:
        raise OneDriveError(f"Erro ao listar pastas no OneDrive: {e}")

    if items:
        return items[0]["id"]

    # Cria a pasta
    create_url = f"{GRAPH_BASE}/me/drive/items/{parent_id}/children"
    payload = {
        "name": folder_name,
        "folder": {},
        "@microsoft.graph.conflictBehavior": "rename",
    }

    try:
        response = requests.post(
            create_url,
            headers={**_headers(access_token), "Content-Type": "application/json"},
            json=payload,
            timeout=15,
        )
        response.raise_for_status()
        folder_id = response.json()["id"]
        logger.info(f"Pasta criada: {folder_name} (id={folder_id})")
        return folder_id
    except requests.RequestException as e:
        raise OneDriveError(f"Erro ao criar pasta '{folder_name}': {e}")


def build_folder_path(pedido_id: str) -> str:
    """Monta o caminho padrão: Pedidos/ANO/MES/pedido_ID."""
    now = datetime.now()
    return f"Pedidos/{now.year}/{now.month:02d}/pedido_{pedido_id}"


# ─── Upload ───────────────────────────────────────────────────────────────────

def upload_file(access_token: str, folder_id: str, file: InMemoryUploadedFile) -> dict:
    """
    Faz upload de um arquivo para uma pasta específica no OneDrive.
    Usa upload simples (até 4 MB) ou upload em sessão (acima de 4 MB).
    Retorna o dict do item criado no OneDrive.
    """
    SIMPLE_UPLOAD_LIMIT = 4 * 1024 * 1024  # 4 MB

    if file.size <= SIMPLE_UPLOAD_LIMIT:
        return _simple_upload(access_token, folder_id, file)
    else:
        return _session_upload(access_token, folder_id, file)


def _simple_upload(access_token: str, folder_id: str, file: InMemoryUploadedFile) -> dict:
    """Upload simples para arquivos até 4 MB."""
    filename = file.name
    url = f"{GRAPH_BASE}/me/drive/items/{folder_id}:/{filename}:/content"

    try:
        response = requests.put(
            url,
            headers={**_headers(access_token), "Content-Type": file.content_type or "application/octet-stream"},
            data=file.read(),
            timeout=60,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        raise OneDriveError(f"Erro no upload de '{filename}': {e}")


def _session_upload(access_token: str, folder_id: str, file: InMemoryUploadedFile) -> dict:
    """Upload em sessão para arquivos maiores que 4 MB."""
    filename = file.name

    # 1. Cria sessão de upload
    session_url = f"{GRAPH_BASE}/me/drive/items/{folder_id}:/{filename}:/createUploadSession"
    payload = {
        "item": {
            "@microsoft.graph.conflictBehavior": "rename",
            "name": filename,
        }
    }
    try:
        response = requests.post(
            session_url,
            headers={**_headers(access_token), "Content-Type": "application/json"},
            json=payload,
            timeout=15,
        )
        response.raise_for_status()
        upload_url = response.json()["uploadUrl"]
    except requests.RequestException as e:
        raise OneDriveError(f"Erro ao criar sessão de upload: {e}")

    # 2. Envia os dados em chunks de 5 MB
    CHUNK_SIZE = 5 * 1024 * 1024
    file_size = file.size
    offset = 0
    last_response = None

    while offset < file_size:
        chunk = file.read(CHUNK_SIZE)
        chunk_len = len(chunk)
        end = offset + chunk_len - 1

        try:
            response = requests.put(
                upload_url,
                headers={
                    "Content-Length": str(chunk_len),
                    "Content-Range": f"bytes {offset}-{end}/{file_size}",
                    "Content-Type": "application/octet-stream",
                },
                data=chunk,
                timeout=120,
            )
            if response.status_code not in (200, 201, 202):
                raise OneDriveError(f"Chunk upload falhou: {response.status_code} {response.text}")
            last_response = response
        except requests.RequestException as e:
            raise OneDriveError(f"Erro durante upload em sessão: {e}")

        offset += chunk_len
        logger.debug(f"Upload '{filename}': {offset}/{file_size} bytes enviados.")

    return last_response.json()


# ─── Link Compartilhado ───────────────────────────────────────────────────────

def create_share_link(access_token: str, item_id: str) -> str:
    """
    Gera um link de compartilhamento 'view' anônimo para o item.
    Retorna a URL do link.
    """
    url = f"{GRAPH_BASE}/me/drive/items/{item_id}/createLink"
    payload = {"type": "view", "scope": "anonymous"}

    try:
        response = requests.post(
            url,
            headers={**_headers(access_token), "Content-Type": "application/json"},
            json=payload,
            timeout=15,
        )
        response.raise_for_status()
        return response.json()["link"]["webUrl"]
    except requests.RequestException as e:
        raise OneDriveError(f"Erro ao gerar link compartilhado para item '{item_id}': {e}")


# ─── Upload Direto (frontend → OneDrive) ─────────────────────────────────────

def criar_upload_session(access_token: str, pedido_id: str, filename: str, file_size: int) -> dict:
    """
    Cria uma sessão de upload no OneDrive e retorna a uploadUrl.
    O frontend usa essa URL para enviar o arquivo diretamente ao OneDrive,
    sem passar pelo Django.
    Retorna: { upload_url, folder_id, item_path }
    """
    folder_path = build_folder_path(pedido_id)
    folder_id = ensure_folder(access_token, folder_path)

    session_url = f"{GRAPH_BASE}/me/drive/items/{folder_id}:/{filename}:/createUploadSession"
    payload = {
        "item": {
            "@microsoft.graph.conflictBehavior": "rename",
            "name": filename,
        }
    }

    try:
        response = requests.post(
            session_url,
            headers={**_headers(access_token), "Content-Type": "application/json"},
            json=payload,
            timeout=15,
        )
        response.raise_for_status()
        upload_url = response.json()["uploadUrl"]
    except requests.RequestException as e:
        raise OneDriveError(f"Erro ao criar sessão de upload para '{filename}': {e}")

    logger.info(f"Sessão de upload criada para '{filename}' no pedido '{pedido_id}'")
    return {
        "upload_url": upload_url,
        "folder_id": folder_id,
        "filename": filename,
        "file_size": file_size,
    }


def finalizar_upload_direto(access_token: str, item_id: str, pedido_id: str, filename: str, file_size: int, tipo_arquivo: str) -> dict:
    """
    Chamado após o frontend concluir o upload direto.
    Gera o link compartilhado e retorna os metadados para salvar no banco.
    """
    share_url = create_share_link(access_token, item_id)

    return {
        "pedido": pedido_id,
        "nome_arquivo": filename,
        "url_onedrive": share_url,
        "tamanho_bytes": file_size,
        "tipo_arquivo": tipo_arquivo,
        "onedrive_item_id": item_id,
    }


# ─── Orquestrador principal ───────────────────────────────────────────────────

def upload_files_to_pedido(access_token: str, pedido_id: str, files: list) -> list[dict]:
    """
    Orquestra o processo completo para um pedido:
    1. Resolve/cria estrutura de pastas
    2. Faz upload de cada arquivo
    3. Gera link compartilhado
    Retorna lista de dicts com metadados de cada arquivo processado.
    """
    folder_path = build_folder_path(pedido_id)
    folder_id = ensure_folder(access_token, folder_path)
    logger.info(f"Pasta garantida: '{folder_path}' (id={folder_id})")

    results = []
    for file in files:
        logger.info(f"Iniciando upload: '{file.name}' ({file.size} bytes)")
        item = upload_file(access_token, folder_id, file)
        item_id = item["id"]
        share_url = create_share_link(access_token, item_id)

        results.append({
            "nome_arquivo": file.name,
            "url_onedrive": share_url,
            "tamanho_bytes": file.size,
            "tipo_arquivo": file.content_type or "",
            "onedrive_item_id": item_id,
        })
        logger.info(f"Upload concluído: '{file.name}' → {share_url}")

    return results
