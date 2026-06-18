from rest_framework import serializers
from .models import ArquivoPedido


class ArquivoPedidoSerializer(serializers.ModelSerializer):
    class Meta:
        model = ArquivoPedido
        fields = [
            "id",
            "pedido",
            "nome_arquivo",
            "url_onedrive",
            "tamanho_bytes",
            "tipo_arquivo",
            "criado_em",
        ]
        read_only_fields = fields


class UploadRequestSerializer(serializers.Serializer):
    pedido = serializers.CharField(max_length=100)
    arquivos = serializers.ListField(
        child=serializers.FileField(),
        allow_empty=False,
        max_length=20,
    )

    def validate_pedido(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("O campo 'pedido' não pode ser vazio.")
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
        if not all(c in allowed for c in value):
            raise serializers.ValidationError(
                "Use apenas letras, números, hífen e underscore."
            )
        return value
