# Task 00 — Estrutura Base do Projeto

## Objetivo
Criar a estrutura inicial do projeto FastAPI com todos os arquivos de configuração, pastas e dependências necessárias para o desenvolvimento.

## Arquivos a Criar

```
hayashi-api/
├── main.py
├── routers/
│   ├── __init__.py
│   ├── importar.py
│   └── status.py
├── services/
│   ├── __init__.py
│   ├── scraping.py
│   └── sheets.py
├── models/
│   ├── __init__.py
│   └── importacao.py
├── database.py
├── config.py
├── requirements.txt
├── .env.example
├── Dockerfile
└── .dockerignore
```

## Implementação

### `requirements.txt`
```
fastapi==0.111.0
uvicorn[standard]==0.29.0
sqlalchemy==2.0.30
alembic==1.13.1
psycopg2-binary==2.9.9
pydantic==2.7.1
pydantic-settings==2.2.1
playwright==1.44.0
google-api-python-client==2.130.0
google-auth==2.29.0
httpx==0.27.0
python-dotenv==1.0.1
```

### `main.py`
- Instanciar `FastAPI` com título "Hayashi API" e versão "1.0.0"
- Incluir os routers: `importar` (prefix `/importar`) e `status` (prefix `/status`)
- Adicionar rota `GET /health` diretamente no main que retorna `{"status": "ok"}`
- Adicionar middleware de CORS permitindo apenas a origem do frontend (`FRONTEND_URL` do env)

### `config.py`
- Usar `pydantic-settings` com `BaseSettings`
- Campos: `DATABASE_URL`, `IFRUTI_URL`, `IFRUTI_EMAIL`, `IFRUTI_PASSWORD`, `API_SECRET_KEY`, `SPREADSHEET_ID`, `GOOGLE_SERVICE_ACCOUNT_EMAIL`, `GOOGLE_PRIVATE_KEY`, `FRONTEND_URL`
- Instanciar `settings = Settings()` no final do arquivo

### `database.py`
- Criar engine SQLAlchemy com `DATABASE_URL` do config
- Criar `SessionLocal` e `Base`
- Criar função `get_db()` como dependency do FastAPI

### `.env.example`
```
DATABASE_URL=postgresql://user:pass@localhost:5432/hayashi
IFRUTI_URL=https://ifruti.com.br
IFRUTI_EMAIL=
IFRUTI_PASSWORD=
API_SECRET_KEY=
SPREADSHEET_ID=
GOOGLE_SERVICE_ACCOUNT_EMAIL=
GOOGLE_PRIVATE_KEY=
FRONTEND_URL=https://app.hayashi.asynnc.cloud
```

### `Dockerfile`
```dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y gcc libpq-dev && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium --with-deps
COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### `.dockerignore`
```
.env
__pycache__/
*.pyc
.git/
```

## Critérios de Aceitação
- `uvicorn main:app --reload` sobe sem erros
- `GET /health` retorna `{"status": "ok"}` com status 200
- Todos os módulos importam sem erros (mesmo com implementações vazias nos routers/services)
