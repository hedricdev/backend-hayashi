# Task 08 — Dockerfile e Deploy no EasyPanel

## Objetivo
Garantir que o container Docker funcione corretamente no EasyPanel (VPS Hostinger), com Playwright instalado em modo headless e todas as variáveis de ambiente configuradas.

## Arquivos a Editar/Criar

- `Dockerfile` (revisar o criado na task 00)
- `docker-compose.yml` (apenas para desenvolvimento local)

## Implementação

### `Dockerfile` (produção)
O Playwright precisa de dependências do sistema para rodar Chromium em containers slim. Usar a versão completa das deps:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Dependências do sistema para Playwright + Chromium
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libgbm1 \
    libasound2 \
    libxshmfence1 \
    libgles2 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Instalar apenas Chromium (mais leve que instalar todos os browsers)
RUN playwright install chromium

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### `docker-compose.yml` (desenvolvimento local)
```yaml
version: "3.9"
services:
  api:
    build: .
    ports:
      - "8000:8000"
    env_file:
      - .env
    depends_on:
      - postgres

  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: hayashi
      POSTGRES_PASSWORD: hayashi
      POSTGRES_DB: hayashi
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  pgdata:
```

### Configuração no EasyPanel

No EasyPanel, criar um novo serviço do tipo **App** com:
- **Repositório**: `hedricdev/hayashi-api` (branch `main`)
- **Build**: Dockerfile (automático)
- **Porta**: 8000
- **Domínio**: `api.hayashi.asynnc.cloud`
- **Variáveis de ambiente**: adicionar todas as do `.env.example` com os valores reais

O PostgreSQL já deve estar rodando como serviço separado no EasyPanel com rede interna. A `DATABASE_URL` deve usar o hostname interno do container PostgreSQL no EasyPanel.

### Migrações em produção
Rodar as migrações manualmente via terminal do EasyPanel após o primeiro deploy:
```bash
alembic upgrade head
```

Ou adicionar ao `CMD` do Dockerfile (cuidado: só funciona se o banco já estiver disponível na inicialização):
```dockerfile
CMD ["sh", "-c", "alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port 8000"]
```

## Critérios de Aceitação
- `docker build -t hayashi-api .` conclui sem erros localmente
- `docker-compose up` sobe API + PostgreSQL localmente
- `GET https://api.hayashi.asynnc.cloud/health` retorna `{"status": "ok"}` após deploy
- Playwright roda em modo headless dentro do container sem erros de dependência
