from django.db import models


class MicrosoftToken(models.Model):
    """
    Armazena os tokens OAuth2 da Microsoft por usuário.
    Garante que access_token e refresh_token sobrevivam
    a reinicializações do servidor, independente da sessão.
    """
    user_email = models.EmailField(unique=True, db_index=True)
    access_token = models.TextField()
    refresh_token = models.TextField(blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Token Microsoft"
        verbose_name_plural = "Tokens Microsoft"

    def __str__(self):
        return f"Token de {self.user_email} (atualizado em {self.atualizado_em:%d/%m/%Y %H:%M})"

    def is_expired(self) -> bool:
        from django.utils import timezone
        if not self.expires_at:
            return False
        return timezone.now() >= self.expires_at


class ArquivoPedido(models.Model):
    pedido = models.CharField(max_length=100, db_index=True)
    nome_arquivo = models.CharField(max_length=255)
    url_onedrive = models.URLField(max_length=2048)
    tamanho_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    tipo_arquivo = models.CharField(max_length=100, blank=True)
    onedrive_item_id = models.CharField(max_length=512, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "Arquivo de Pedido"
        verbose_name_plural = "Arquivos de Pedidos"

    def __str__(self):
        return f"[{self.pedido}] {self.nome_arquivo}"
