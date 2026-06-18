import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from core.exceptions import OneDriveError, FileSizeExceededError, InvalidFileTypeError, MicrosoftAuthError
from apps.auth_ms.services import get_valid_token
from .models import ArquivoPedido
from .serializers import ArquivoPedidoSerializer, UploadRequestSerializer
from .validators import validate_pedido_id, validate_files
from .services import upload_files_to_pedido, criar_upload_session, finalizar_upload_direto

logger = logging.getLogger(__name__)


def _get_token(request):
    try:
        return get_valid_token(request), None
    except MicrosoftAuthError as e:
        return None, Response(
            {"success": False, "error": {"code": 401, "message": str(e)}},
            status=status.HTTP_401_UNAUTHORIZED,
        )


class UploadArquivoView(APIView):
    """
    POST /api/pedidos/upload/
    Upload tradicional passando pelo Django (arquivos pequenos).
    """

    def post(self, request):
        serializer = UploadRequestSerializer(data={
            "pedido": request.data.get("pedido"),
            "arquivos": request.FILES.getlist("arquivos"),
        })

        if not serializer.is_valid():
            return Response(
                {"success": False, "error": {"code": 400, "message": serializer.errors}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        pedido_id = serializer.validated_data["pedido"]
        files = serializer.validated_data["arquivos"]

        try:
            validate_pedido_id(pedido_id)
            validate_files(files)
        except (ValueError, FileSizeExceededError, InvalidFileTypeError) as e:
            return Response(
                {"success": False, "error": {"code": 400, "message": str(e)}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        access_token, err = _get_token(request)
        if err:
            return err

        try:
            uploaded = upload_files_to_pedido(access_token, pedido_id, files)
        except OneDriveError as e:
            return Response(
                {"success": False, "error": {"code": 502, "message": str(e)}},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        created = []
        for item in uploaded:
            arquivo = ArquivoPedido.objects.create(pedido=pedido_id, **item)
            created.append(arquivo)

        serializer_out = ArquivoPedidoSerializer(created, many=True)
        logger.info(f"Upload concluído: pedido={pedido_id}, arquivos={len(created)}")

        return Response(
            {
                "success": True,
                "message": f"{len(created)} arquivo(s) enviado(s) com sucesso.",
                "data": serializer_out.data,
            },
            status=status.HTTP_201_CREATED,
        )


class IniciarUploadDiretoView(APIView):
    """
    POST /api/pedidos/upload-direto/iniciar/
    Cria uma sessão de upload no OneDrive e retorna a uploadUrl.
    O frontend usa essa URL para enviar o arquivo diretamente ao OneDrive.

    Body JSON:
    {
        "pedido": "pedido-123",
        "filename": "video.mp4",
        "file_size": 104857600
    }
    """

    def post(self, request):
        pedido_id = request.data.get("pedido", "").strip()
        filename = request.data.get("filename", "").strip()
        file_size = request.data.get("file_size", 0)

        if not pedido_id:
            return Response(
                {"success": False, "error": {"code": 400, "message": "Campo 'pedido' obrigatório."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not filename:
            return Response(
                {"success": False, "error": {"code": 400, "message": "Campo 'filename' obrigatório."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            validate_pedido_id(pedido_id)
        except ValueError as e:
            return Response(
                {"success": False, "error": {"code": 400, "message": str(e)}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        access_token, err = _get_token(request)
        if err:
            return err

        try:
            session = criar_upload_session(access_token, pedido_id, filename, file_size)
        except OneDriveError as e:
            return Response(
                {"success": False, "error": {"code": 502, "message": str(e)}},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response({"success": True, "data": session})


class FinalizarUploadDiretoView(APIView):
    """
    POST /api/pedidos/upload-direto/finalizar/
    Chamado pelo frontend após concluir o upload direto ao OneDrive.
    Gera o link compartilhado e salva no banco.

    Body JSON:
    {
        "pedido": "pedido-123",
        "filename": "video.mp4",
        "file_size": 104857600,
        "tipo_arquivo": "video/mp4",
        "onedrive_item_id": "ABC123..."
    }
    """

    def post(self, request):
        pedido_id = request.data.get("pedido", "").strip()
        filename = request.data.get("filename", "").strip()
        file_size = request.data.get("file_size", 0)
        tipo_arquivo = request.data.get("tipo_arquivo", "")
        item_id = request.data.get("onedrive_item_id", "").strip()

        if not all([pedido_id, filename, item_id]):
            return Response(
                {"success": False, "error": {"code": 400, "message": "Campos obrigatórios: pedido, filename, onedrive_item_id."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        access_token, err = _get_token(request)
        if err:
            return err

        try:
            metadados = finalizar_upload_direto(access_token, item_id, pedido_id, filename, file_size, tipo_arquivo)
        except OneDriveError as e:
            return Response(
                {"success": False, "error": {"code": 502, "message": str(e)}},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        arquivo = ArquivoPedido.objects.create(**metadados)
        logger.info(f"Upload direto finalizado: pedido={pedido_id}, arquivo={filename}")

        return Response(
            {
                "success": True,
                "message": "Arquivo registrado com sucesso.",
                "data": ArquivoPedidoSerializer(arquivo).data,
            },
            status=status.HTTP_201_CREATED,
        )


class ListarArquivosPedidoView(APIView):
    """GET /api/pedidos/<pedido_id>/arquivos/"""

    def get(self, request, pedido_id: str):
        try:
            pedido_id = validate_pedido_id(pedido_id)
        except ValueError as e:
            return Response(
                {"success": False, "error": {"code": 400, "message": str(e)}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        arquivos = ArquivoPedido.objects.filter(pedido=pedido_id)

        if not arquivos.exists():
            return Response(
                {"success": False, "error": {"code": 404, "message": f"Nenhum arquivo encontrado para o pedido '{pedido_id}'."}},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = ArquivoPedidoSerializer(arquivos, many=True)
        return Response({
            "success": True,
            "data": {
                "pedido": pedido_id,
                "total": arquivos.count(),
                "arquivos": serializer.data,
            }
        })


class DetalheArquivoView(APIView):
    """GET/DELETE /api/pedidos/arquivos/<pk>/"""

    def _get_object(self, pk):
        try:
            return ArquivoPedido.objects.get(pk=pk)
        except ArquivoPedido.DoesNotExist:
            return None

    def get(self, request, pk: int):
        arquivo = self._get_object(pk)
        if not arquivo:
            return Response(
                {"success": False, "error": {"code": 404, "message": "Arquivo não encontrado."}},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response({"success": True, "data": ArquivoPedidoSerializer(arquivo).data})

    def delete(self, request, pk: int):
        arquivo = self._get_object(pk)
        if not arquivo:
            return Response(
                {"success": False, "error": {"code": 404, "message": "Arquivo não encontrado."}},
                status=status.HTTP_404_NOT_FOUND,
            )
        arquivo.delete()
        logger.info(f"Arquivo id={pk} removido do banco.")
        return Response({"success": True, "message": "Arquivo removido com sucesso."})



def _get_token(request):
    """
    Helper: retorna access_token válido ou lança Response de erro.
    Usar com: token, err = _get_token(request); if err: return err
    """
    try:
        return get_valid_token(request), None
    except MicrosoftAuthError as e:
        return None, Response(
            {"success": False, "error": {"code": 401, "message": str(e)}},
            status=status.HTTP_401_UNAUTHORIZED,
        )


class UploadArquivoView(APIView):
    """
    POST /api/pedidos/upload/
    Body: multipart/form-data
      - pedido: str
      - arquivos: File[]
    """

    def post(self, request):
        serializer = UploadRequestSerializer(data={
            "pedido": request.data.get("pedido"),
            "arquivos": request.FILES.getlist("arquivos"),
        })

        if not serializer.is_valid():
            return Response(
                {"success": False, "error": {"code": 400, "message": serializer.errors}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        pedido_id = serializer.validated_data["pedido"]
        files = serializer.validated_data["arquivos"]

        # Validações de arquivo
        try:
            validate_pedido_id(pedido_id)
            validate_files(files)
        except (ValueError, FileSizeExceededError, InvalidFileTypeError) as e:
            return Response(
                {"success": False, "error": {"code": 400, "message": str(e)}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Token sempre válido — renova automaticamente se necessário
        access_token, err = _get_token(request)
        if err:
            return err

        # Upload e criação de pastas no OneDrive
        try:
            uploaded = upload_files_to_pedido(access_token, pedido_id, files)
        except OneDriveError as e:
            return Response(
                {"success": False, "error": {"code": 502, "message": str(e)}},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # Persiste no banco
        created = []
        for item in uploaded:
            arquivo = ArquivoPedido.objects.create(pedido=pedido_id, **item)
            created.append(arquivo)

        serializer_out = ArquivoPedidoSerializer(created, many=True)
        logger.info(f"Upload concluído: pedido={pedido_id}, arquivos={len(created)}")

        return Response(
            {
                "success": True,
                "message": f"{len(created)} arquivo(s) enviado(s) com sucesso.",
                "data": serializer_out.data,
            },
            status=status.HTTP_201_CREATED,
        )


class ListarArquivosPedidoView(APIView):
    """
    GET /api/pedidos/<pedido_id>/arquivos/
    Lista todos os arquivos vinculados a um pedido.
    """

    def get(self, request, pedido_id: str):
        try:
            pedido_id = validate_pedido_id(pedido_id)
        except ValueError as e:
            return Response(
                {"success": False, "error": {"code": 400, "message": str(e)}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        arquivos = ArquivoPedido.objects.filter(pedido=pedido_id)

        if not arquivos.exists():
            return Response(
                {"success": False, "error": {"code": 404, "message": f"Nenhum arquivo encontrado para o pedido '{pedido_id}'."}},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = ArquivoPedidoSerializer(arquivos, many=True)
        return Response({
            "success": True,
            "data": {
                "pedido": pedido_id,
                "total": arquivos.count(),
                "arquivos": serializer.data,
            }
        })


class DetalheArquivoView(APIView):
    """
    GET    /api/pedidos/arquivos/<pk>/  → detalhe
    DELETE /api/pedidos/arquivos/<pk>/  → remove do banco
    """

    def _get_object(self, pk):
        try:
            return ArquivoPedido.objects.get(pk=pk)
        except ArquivoPedido.DoesNotExist:
            return None

    def get(self, request, pk: int):
        arquivo = self._get_object(pk)
        if not arquivo:
            return Response(
                {"success": False, "error": {"code": 404, "message": "Arquivo não encontrado."}},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response({"success": True, "data": ArquivoPedidoSerializer(arquivo).data})

    def delete(self, request, pk: int):
        arquivo = self._get_object(pk)
        if not arquivo:
            return Response(
                {"success": False, "error": {"code": 404, "message": "Arquivo não encontrado."}},
                status=status.HTTP_404_NOT_FOUND,
            )
        arquivo.delete()
        logger.info(f"Arquivo id={pk} removido do banco.")
        return Response({"success": True, "message": "Arquivo removido com sucesso."})
