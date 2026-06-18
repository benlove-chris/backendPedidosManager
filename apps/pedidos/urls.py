from django.urls import path
from .views import (
    UploadArquivoView,
    IniciarUploadDiretoView,
    FinalizarUploadDiretoView,
    ListarArquivosPedidoView,
    DetalheArquivoView,
)

urlpatterns = [
    path("api/pedidos/upload/", UploadArquivoView.as_view(), name="pedido-upload"),
    path("api/pedidos/upload-direto/iniciar/", IniciarUploadDiretoView.as_view(), name="upload-direto-iniciar"),
    path("api/pedidos/upload-direto/finalizar/", FinalizarUploadDiretoView.as_view(), name="upload-direto-finalizar"),
    path("api/pedidos/<str:pedido_id>/arquivos/", ListarArquivosPedidoView.as_view(), name="pedido-listar"),
    path("api/pedidos/arquivos/<int:pk>/", DetalheArquivoView.as_view(), name="arquivo-detalhe"),
]
