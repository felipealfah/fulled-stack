"""
Endpoints de gestão de keywords — Phase 32.
NÃO adicionar Depends de auth: middleware global em main.py cuida disso (decisão D-09).

## Fase 35 / D-02 — `kw_staging` e as tabelas de scorecard moram no Supabase
ADR: Full_AIOS_LEADGEN/inteligence/decisoes/2026-08-29_Migracao_LeadGen_Postgres_Supabase.md

Este router atravessa a fronteira dos dois bancos:
  - `pesquisas` e `projetos` (camada de **decisão**) continuam no Postgres da Stack;
  - `kw_staging`, `kw_classification_overrides`, `scorecard_overrides` e `kw_scorecard`
    (camada **pré-decisão**) passaram para o schema `leadgen` no Supabase.

Consequência estrutural: não existe mais FK atravessando a fronteira. O que o banco
garantia — titularidade da keyword e limpeza em cascata — passa a ser responsabilidade
explícita destes handlers.
"""
import sys

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from db import get_pool
from db_leadgen import get_lg_pool

ALLOWED_KW_TYPES = {
    "PAGINA_PRINCIPAL", "PAGINA_GEO", "LOCALIDADE",
    "SECAO", "SURPRESA", "DESCARTA", "SERVICO"
}

PROJETO_STATUS_LIVE = ("deploy", "monetizacao", "manutencao")

router = APIRouter(prefix="/pesquisas", tags=["kw-mgmt"])

# Fase 35 / D-02: uma instrução para o lote inteiro (o contrato aceita até 2000 itens).
# O `AND kw_staging.pesquisa_id = $3::uuid` repete no próprio banco o filtro de
# titularidade que a FK garantia — é o que impede um `keyword_id` forjado no corpo
# atingir keyword de outra pesquisa (T-35-05). O `RETURNING` devolve exatamente os ids
# que casaram, dispensando o SELECT de descoberta que existia antes.
_SQL_BULK_RECLASSIFY = """
UPDATE kw_staging
   SET kw_type    = t.tipo,
       updated_at = NOW()
  FROM unnest($1::int[], $2::text[]) AS t(id, tipo)
 WHERE kw_staging.id = t.id
   AND kw_staging.pesquisa_id = $3::uuid
RETURNING kw_staging.id
"""


def _e_uuid_malformado(e: Exception) -> bool:
    """Distingue 'o path param não é UUID' de qualquer outra falha do banco.

    O `except Exception` genérico que existia aqui transformava *qualquer* erro — pool
    indisponível, timeout, permissão — num 422 'pesquisa_id não é um UUID válido',
    escondendo a causa real. Mesmo tratamento adotado em `intel.py` na Fase 35.
    """
    msg = str(e).lower()
    return "invalid input syntax" in msg or "uuid" in msg


class ReclassifyItem(BaseModel):
    keyword_id: int
    kw_type: str


class BulkReclassifyRequest(BaseModel):
    items: list[ReclassifyItem] = Field(..., min_length=1, max_length=2000)


@router.patch("/{pesquisa_id}/keywords/bulk-reclassify")
async def bulk_reclassify(pesquisa_id: str, body: BulkReclassifyRequest):
    """Reclassifica `kw_type` de um lote de keywords. Nunca 500 global.

    ## Fase 35 / D-02 — dois passos, um round-trip de escrita
    ADR: Full_AIOS_LEADGEN/inteligence/decisoes/2026-08-29_Migracao_LeadGen_Postgres_Supabase.md

    1. `c_pg` (Postgres da Stack) confere a existência da pesquisa — `pesquisas` é camada
       de decisão e não migrou. Sem FK cross-DB este passo é o primeiro controle de
       titularidade (T-35-05); o `WHERE` do UPDATE o repete no outro banco.
    2. `c_lg` (Supabase) executa **uma única** instrução para o lote inteiro.

    O laço item a item que existia aqui emitia um `execute` por keyword. Com o banco em
    `localhost` era um round-trip local; depois do corte cada volta atravessa a internet,
    e o contrato aceita `max_length=2000` — seriam 2000 RTTs por request. Em lote o custo
    de rede é **constante** (Pitfall 8).
    """
    invalid = []

    # Fase 35 / D-02: passo 1 — `pesquisas` continua no Postgres da Stack.
    pg = await get_pool()
    async with pg.acquire() as c_pg:
        try:
            exists = await c_pg.fetchval(
                "SELECT 1 FROM pesquisas WHERE id = $1::uuid",
                pesquisa_id,
            )
        except Exception as e:
            if _e_uuid_malformado(e):
                raise HTTPException(422, "pesquisa_id não é um UUID válido")
            raise
        if not exists:
            raise HTTPException(404, "Pesquisa não encontrada")

    valid_items = []
    for item in body.items:
        if item.kw_type not in ALLOWED_KW_TYPES:
            invalid.append({
                "id": item.keyword_id,
                "reason": f"kw_type inválido: '{item.kw_type}'. Aceitos: {sorted(ALLOWED_KW_TYPES)}",
            })
        else:
            valid_items.append(item)

    if not valid_items:
        return {"updated": 0, "not_found": [], "invalid": invalid}

    ids = [i.keyword_id for i in valid_items]

    # Deduplicação por keyword_id mantendo a ÚLTIMA ocorrência: é o estado que o laço
    # item a item deixava no banco (cada escrita sobrescrevia a anterior). Sem isso o
    # `unnest` daria duas linhas-fonte para a mesma linha-alvo e o Postgres escolheria
    # uma delas de forma não determinística.
    por_id = {i.keyword_id: i for i in valid_items}
    lote = list(por_id.values())

    # Fase 35 / D-02: passo 2 — uma ida à rede, qualquer que seja o tamanho do lote.
    lg = await get_lg_pool()
    async with lg.acquire() as c_lg:
        async with c_lg.transaction():
            rows = await c_lg.fetch(
                _SQL_BULK_RECLASSIFY,
                [i.keyword_id for i in lote],
                [i.kw_type for i in lote],
                pesquisa_id,
            )

    existentes = {r["id"] for r in rows}
    # Contagem idêntica à do laço anterior: um por item válido cuja linha existe na pesquisa.
    updated = sum(1 for i in valid_items if i.keyword_id in existentes)
    not_found = [i for i in ids if i not in existentes]

    return {"updated": updated, "not_found": not_found, "invalid": invalid}


# Fase 35 / D-06 — o que o `DELETE FROM pesquisas` disparava sozinho no banco.
# Conferidas no catálogo do Postgres vivo (`pg_constraint` com `confrelid = 'pesquisas'`),
# NÃO na documentação nem na migration de origem — foi assim que o Plan 35-04 descobriu
# que a lista dele estava incompleta.
#
# `confdeltype = 'c'` (CASCADE) e `'a'` (NO ACTION) → a linha filha deixa de existir:
_TABELAS_APAGAR = (
    "kw_classification_overrides",   # 'a' — já era apagada à mão; só muda de conexão
    "scorecard_overrides",           # 'a' — idem
    "kw_scorecard",                  # 'a' — idem
    "kw_staging",                    # 'c' — a novidade: dependia do CASCADE do banco
)
# `confdeltype = 'n'` (SET NULL) → a linha filha SOBREVIVE, só perde o vínculo. Apagar
# aqui destruiria conteúdo publicado; o comportamento a preservar é o nullify.
_TABELAS_NULIFICAR = (
    "content_pages",
    "projeto_seo_plan_pages",
)


@router.delete("/{pesquisa_id}")
async def delete_pesquisa(pesquisa_id: str, force: bool = False):
    """Apaga a pesquisa e tudo que dependia dela.

    ## Fase 35 / D-06 — o cascade do banco não existe mais
    ADR: Full_AIOS_LEADGEN/inteligence/decisoes/2026-08-29_Migracao_LeadGen_Postgres_Supabase.md

    Antes, um único `DELETE FROM pesquisas` disparava as FKs de 6 tabelas. Todas as 6
    moram agora no Supabase e não há FK atravessando a fronteira dos bancos: sem limpeza
    explícita o delete passaria a deixar lixo invisível (`kw_staging`) e vínculos
    apontando para uma pesquisa que não existe mais (`content_pages`). As três etapas
    abaixo são ordenadas de propósito.

    Filhos primeiro, pesquisa por último: a intenção do endpoint é destrutiva, então uma
    falha no passo 3 deixa a pesquisa viva **sem** keywords, e reexecutar o `DELETE`
    converge (o passo 2 vira no-op). A ordem inversa deixaria órfãos permanentes e
    invisíveis.

    A guarda 409 de projeto em produção é avaliada no passo 1 — antes de qualquer escrita,
    em qualquer um dos dois bancos.
    """
    # Passo 1 — Postgres da Stack: guarda e resolução. Nenhuma escrita aqui.
    pg = await get_pool()
    async with pg.acquire() as c_pg:
        try:
            row = await c_pg.fetchrow(
                """SELECT p.id, p.projeto_id_uuid, proj.status AS projeto_status
                   FROM pesquisas p
                   LEFT JOIN projetos proj ON proj.id = p.projeto_id_uuid
                   WHERE p.id = $1::uuid""",
                pesquisa_id,
            )
        except Exception as e:
            if _e_uuid_malformado(e):
                raise HTTPException(422, "pesquisa_id não é um UUID válido")
            raise

        if not row:
            raise HTTPException(404, "Pesquisa não encontrada")

        if row["projeto_status"] in PROJETO_STATUS_LIVE and not force:
            raise HTTPException(
                409,
                "Pesquisa pertence a projeto em produção (status=" + row["projeto_status"] + ") — passe ?force=true para forçar",
            )

    # Passo 2 — Fase 35 / D-06: limpar os filhos no Supabase, numa transação só.
    # O `RETURNING id` do `kw_staging` é a contagem real de keywords removidas — é o valor
    # que o subselect `kw_count` devolvia antes de a tabela mudar de banco.
    lg = await get_lg_pool()
    async with lg.acquire() as c_lg:
        async with c_lg.transaction():
            for tabela in _TABELAS_APAGAR:
                if tabela == "kw_staging":
                    continue  # tratada abaixo — precisa do RETURNING para a contagem
                # noqa S608: o identificador vem de _TABELAS_APAGAR (constante do módulo),
                # nunca de entrada do usuário; o único valor continua parametrizado em $1
                # (T-35-06). É o caso de identificador dinâmico que o CLAUDE.md abre como
                # exceção — nome de tabela por f-string, valor nunca.
                await c_lg.execute(
                    f"DELETE FROM {tabela} WHERE pesquisa_id = $1::uuid", pesquisa_id,  # noqa: S608
                )
            apagadas = await c_lg.fetch(
                "DELETE FROM kw_staging WHERE pesquisa_id = $1::uuid RETURNING id",
                pesquisa_id,
            )
            deleted_keywords = len(apagadas)
            for tabela in _TABELAS_NULIFICAR:
                await c_lg.execute(
                    f"UPDATE {tabela} SET pesquisa_id = NULL WHERE pesquisa_id = $1::uuid",  # noqa: S608
                    pesquisa_id,
                )

    # Passo 3 — só então o Postgres. `agent_executions` e `projetos` não migraram.
    try:
        async with pg.acquire() as c_pg:
            async with c_pg.transaction():
                await c_pg.execute("DELETE FROM agent_executions WHERE pesquisa_id = $1::uuid", pesquisa_id)
                await c_pg.execute(
                    "UPDATE projetos SET pesquisa_id_atual = NULL WHERE pesquisa_id_atual = $1::uuid",
                    pesquisa_id,
                )
                await c_pg.execute("DELETE FROM pesquisas WHERE id = $1::uuid", pesquisa_id)
    except Exception as e:
        # Nunca falhar mudo: os filhos já foram apagados e a pesquisa continua de pé.
        print(
            f"[kw_mgmt] WARN: filhos da pesquisa {pesquisa_id} apagados no Supabase mas o "
            f"DELETE no Postgres falhou: {type(e).__name__}",
            file=sys.stderr,
        )
        raise HTTPException(
            500,
            "As keywords e os dados dependentes da pesquisa foram apagados, mas a pesquisa "
            "em si não pôde ser removida. Reexecute o DELETE para concluir — a operação é "
            "idempotente.",
        )

    return {"deleted_keywords": deleted_keywords, "soft": False}
