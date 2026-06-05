# Task 01 — Modelos do Banco de Dados

## Objetivo
Definir os modelos SQLAlchemy e configurar o Alembic. A tabela `usuarios` (criada em Task 02) é importada aqui para que o Alembic gere a migration completa de uma vez.

## Arquivos a Criar/Editar

- `models/importacao.py` — modelos SQLAlchemy de importação
- `alembic.ini` — configuração do Alembic
- `alembic/` — pasta gerada pelo Alembic (`alembic init alembic`)
- `alembic/env.py` — ajustar para importar todos os modelos

---

## Implementação

### `models/importacao.py`

Duas tabelas:

**`importacoes`**
| Coluna | Tipo | Detalhes |
|--------|------|---------|
| id | Integer | PK, autoincrement |
| iniciado_em | DateTime | default utcnow |
| finalizado_em | DateTime | nullable |
| status | String(20) | `"em_andamento"` / `"sucesso"` / `"erro"` |
| total_importado | Integer | default 0 |
| total_erro | Integer | default 0 |
| log | Text | nullable — JSON string com lista de erros |

**`clientes_vendedor`**
| Coluna | Tipo | Detalhes |
|--------|------|---------|
| id | Integer | PK, autoincrement |
| cliente_nome | String(200) | not null |
| vendedor_id | Integer | FK → **usuarios.id** (cascade delete) |
| ativo | Boolean | default True |

> A tabela `vendedores` presente no rascunho inicial foi removida. Usuários com `role = "vendedor"` substituem essa tabela. A FK `vendedor_id` aponta diretamente para `usuarios.id` (model criado na Task 02).

---

### `alembic/env.py`

Importar **todos** os modelos antes de gerar a migration, para que o Alembic os detecte:

```python
from config import settings
from database import Base

# importar todos os modelos para registrar os metadados no Base
import models.usuario      # Task 02
import models.importacao   # esta task

target_metadata = Base.metadata

def run_migrations_online():
    config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
    # ... resto do boilerplate padrão do alembic
```

---

## Comandos para Executar

> **Atenção**: rodar apenas após Task 02 estar implementada, pois `models/usuario.py` precisa existir.

```bash
alembic init alembic
# editar alembic/env.py conforme acima
alembic revision --autogenerate -m "initial tables"
alembic upgrade head
```

---

## Critérios de Aceitação

- `alembic upgrade head` cria as tabelas `usuarios`, `importacoes` e `clientes_vendedor` sem erros
- FK `clientes_vendedor.vendedor_id → usuarios.id` existe no banco
- `alembic downgrade base` desfaz todas as tabelas sem erros
- Modelos importam corretamente sem circular imports
