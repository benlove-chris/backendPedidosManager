# Backend Django + OneDrive

## Estrutura

```
backend/
├── apps/
│   ├── auth_ms/          # OAuth2 Microsoft
│   │   ├── services.py   # lógica de token
│   │   ├── views.py
│   │   └── urls.py
│   └── pedidos/          # upload e listagem
│       ├── models.py
│       ├── serializers.py
│       ├── validators.py
│       ├── services.py   # lógica OneDrive
│       ├── views.py
│       └── urls.py
├── config/
│   ├── settings.py
│   └── urls.py
├── core/
│   ├── exceptions.py     # handler global + exceções custom
│   └── middleware.py     # proteção de rotas via sessão
├── requirements.txt
└── .env.example
```

---

## Setup

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# edite .env com suas credenciais

python manage.py migrate
python manage.py runserver
```

---

## Endpoints

### Autenticação

| Método | URL | Descrição |
|--------|-----|-----------|
| GET | `/login/` | Redireciona para login Microsoft |
| GET | `/auth/callback/` | Callback OAuth2, salva sessão |
| GET | `/api/auth/me/` | Dados do usuário logado |
| POST | `/api/auth/logout/` | Encerra sessão |

### Pedidos

| Método | URL | Descrição |
|--------|-----|-----------|
| POST | `/api/pedidos/upload/` | Upload de arquivos para um pedido |
| GET | `/api/pedidos/<pedido_id>/arquivos/` | Lista arquivos de um pedido |
| GET | `/api/pedidos/arquivos/<pk>/` | Detalhe de um arquivo |
| DELETE | `/api/pedidos/arquivos/<pk>/` | Remove registro do banco |

---

## Padrão de resposta da API

**Sucesso:**
```json
{
  "success": true,
  "data": { ... }
}
```

**Erro:**
```json
{
  "success": false,
  "error": {
    "code": 400,
    "message": "Descrição do erro"
  }
}
```

---

## Upload — exemplo com fetch (React)

```js
const formData = new FormData();
formData.append("pedido", "12345");
files.forEach(f => formData.append("arquivos", f));

const res = await fetch("http://localhost:8000/api/pedidos/upload/", {
  method: "POST",
  credentials: "include",   // envia cookie de sessão
  body: formData,
});
const data = await res.json();
```

---

## Validações aplicadas

- Pedido: apenas letras, números, `-` e `_`, máx 100 chars
- Arquivos: máx 20 por requisição, máx 20 MB por arquivo
- Tipos permitidos: JPG, PNG, GIF, WEBP, PDF, DOC, DOCX, XLS, XLSX, TXT, CSV, ZIP
- Upload simples até 4 MB, upload em sessão (chunks) acima disso

---

## Preparação para produção

- Trocar `SESSION_COOKIE_SAMESITE = "None"` e `SESSION_COOKIE_SECURE = True`
- Substituir SQLite por PostgreSQL
- Configurar `ALLOWED_HOSTS` com o domínio real
- Usar variável de ambiente para `SECRET_KEY`
