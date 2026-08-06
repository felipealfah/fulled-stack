# SPEC — Aba LowTicket no Dashboard (Tracker de Ofertas)

> SDD para agentes de dev. Constrói a interface do Board para a operação Low-Ticket dentro do dashboard existente (`Full_AIOS_STACK/frontend`). **O dado vem do Supabase do LowTicket** (não do Postgres/FastAPI do LEADGEN). Regras de negócio da mineração: `Full_AIOS_LOWTICKET/worker/mineracao/REGRAS.md`. Modelo de dados: `.../SCHEMA.md`.

## 1. Objetivo

Dar ao Board a visão e as ações do funil de mineração: ver as ofertas que a máquina qualificou (`alerta`), analisá-las e decidir (**monitorar × descartar**), acompanhar as monitoradas (réplica do Tracker de Ofertas com Δ7d/tendência), e colher as `candidata` para o dossiê. Tudo que a máquina decide sozinha já está nos flows n8n — esta UI é **exclusivamente o lado humano** do ciclo.

## 2. Contexto técnico (respeitar)

- **Repo/paths:** `Full_AIOS_STACK/frontend/src` — `pages/*.tsx` (uma página grande por tela, padrão do repo), `router.tsx`, `components/Sidebar.tsx`, auth via `RequireAuth`.
- **Stack:** React + Vite + TanStack Query v5 + Tailwind inline dark (`bg-gray-950`), semânticas: `emerald` = positivo/GO, `red` = negativo/NO-GO, `amber` = atenção, `font-mono` pervasivo. pt-BR em toda a UI.
- **Fonte de dados: Supabase via `@supabase/supabase-js`** (adicionar dependência). NÃO usar o axios/`lib/api.ts` do FastAPI para nada do LowTicket.
- **Env:** `VITE_LOWTICKET_SUPABASE_URL` e `VITE_LOWTICKET_SUPABASE_PB_KEY` (novas — publishable key do Supabase). Criar `lib/lowticket.ts` exportando o client + tipos + helpers de query.
- **Segurança (aceito na v1):** tabelas sem RLS + anon key no browser = leitura/escrita aberta a quem tiver a chave. Dashboard é interno e atrás de login próprio — aceito pelo Board; evolução futura é proxear pelo FastAPI. Não bloquear a v1 por isso.

## 3. Contrato de dados (Supabase)

**Tabela `ofertas`** (campos usados pela UI): `id, page_id, anunciante, link_ad_library, nicho, tipo_funil, formato_entregavel, oportunidade_infoapp, expert, observacoes, status, n_anuncios_ativos, dias_ativo_oferta, data_primeiro_anuncio_ativo, data_inicio_monitoramento, candidata_raiox, atualizado_em` + campos de **enriquecimento** (preenchidos pelo Flow 4, podem ser null até o agente rodar): `vertical, vertical_risco, preco_visivel, mercado, n_criativos_video, n_criativos_imagem`.

**Enum `status`:** `novo · alerta · em_analise_funil · descartada · monitorando · em_escala · saturada · pausada · candidata`.

**Enum `tipo_funil`:** `Quiz · Quiz + PV · Quiz + VSL · VSL · PV + VSL · PV`.

**View `v_tracker`** (leitura, para a tela Tracker): `id, anunciante, link_ad_library, nicho, tipo_funil, formato_entregavel, oportunidade_infoapp, expert, observacoes, data_inicio_monitoramento, status, dia_1, dia_atual, delta_7d, maximo, minimo, tendencia (subindo|caindo|estavel)`.

**Tabela `observacoes_diarias`** (leitura, sparkline): `oferta_id, data, dia_monitoramento, n_ads_ativos`.

**Tabela `rastros`** (leitura + escrita, aba Rastros): `id, query, grupo (builder|checkout|resposta_direta|nicho), tipo_busca (plataforma|nicho), funil_hint, populacao_observada, status (a_testar|testado|sem_retorno), criado_em`.

**Política de exclusão (doutrina — vale pra TODA a UI):** **não existe delete físico em nenhuma tabela.** "Excluir" oferta = `status = descartada`; "excluir" rastro = `status = sem_retorno`. A série temporal e o cemitério são ativos da operação. Limpeza de erro grosseiro é SQL manual fora da UI.

### Transições de status permitidas NA UI (e somente estas)

| De | Para | Ação na UI | Efeito adicional |
|----|------|-----------|------------------|
| `alerta` | `em_analise_funil` | "Analisar" | — |
| `alerta` / `em_analise_funil` | `monitorando` | "Monitorar" | **setar `data_inicio_monitoramento = hoje`** |
| `alerta` / `em_analise_funil` | `descartada` | "Descartar" | — |
| `monitorando` | `em_escala` \| `saturada` \| `pausada` | override manual no Tracker | — |
| `candidata` | — | (nenhuma transição; ação = abrir dossiê fora da UI) | — |

A UI **nunca** cria/edita `novo` → `alerta` (isso é da máquina) e **nunca** mexe em `n_anuncios_ativos`/datas de coleta. Campos editáveis pelo Board: `nicho, tipo_funil, formato_entregavel, oportunidade_infoapp, expert, observacoes` + as transições acima. Toda mutation seta `atualizado_em = now()`.

## 4. Estrutura da entrega

- **1 rota nova:** `/lowticket` no `router.tsx`, dentro do `RequireAuth`, seção nova **"LowTicket"** no `Sidebar.tsx` (item "Tracker de Ofertas").
- **1 página:** `pages/LowTicket.tsx` com **abas internas** (estado local): `Gate · Tracker · Candidatas · Infoapp · Arquivo · Rastros` — segue o padrão de página única grande do repo.
- **Header persistente** (todas as abas): contadores por status + tamanho da fila infoapp (badge ⭐) + `max(atualizado_em)` como "última atualização".

## 5. Requisitos funcionais

**FR-1 · Header de contadores.** Dado o load da página; Quando busca `ofertas`; Então exibe tiles com contagem por status (novo, alerta, em_analise_funil, monitorando, candidata, descartada+saturada+pausada agregadas como "arquivo") e contador `oportunidade_infoapp=true`. Tiles clicáveis navegam pra aba correspondente.

**FR-2 · Aba Gate (default).** Lista `status IN (alerta, em_analise_funil)` ordenada por `n_anuncios_ativos desc`. Colunas: anunciante, n_ativos, **mix de criativos** ("🎥 X · 🖼 Y" quando `n_criativos_video`/`n_criativos_imagem` não nulos; "—" senão), dias, **nicho** e **mercado** (do enriquecimento; "—" se null), preço (`preco_visivel`), formato (com ⭐ quando `oportunidade_infoapp`), funil (pré-tag ou "—"), status, atualizado_em. **Badge ⚠️ vermelho quando `vertical_risco = true`** (vertical de risco — anti-regra da operação). Botão **"Abrir na Biblioteca"** (`link_ad_library`, `target="_blank"`) em toda linha. Filtro rápido por `mercado` (chips: pt-BR, es-LATAM, en-US, fr, ...).

**FR-3 · Painel de análise.** Clicar numa linha do Gate abre painel lateral/expandido com: dropdowns `tipo_funil` (6 valores) e `formato_entregavel` (educacao/ferramenta/servico/comunidade/fisico/outro), toggle `expert`, toggle `oportunidade_infoapp`, input `nicho`, textarea `observacoes`, botão salvar (grava e seta `em_analise_funil` se vinha de `alerta`). Ações finais: **Monitorar** (→ `monitorando` + `data_inicio_monitoramento = hoje`, confirm dialog) e **Descartar** (→ `descartada`, confirm dialog).

**FR-4 · Aba Tracker.** Lê `v_tracker` filtrando `status IN (monitorando, em_escala, saturada, pausada)`. Colunas da planilha do Board: anunciante, nicho, funil, expert, início do monitoramento, status, **Dia 1, Dia atual, Δ7d** (verde se >0, vermelho se <0, cinza se 0), Máx, Mín, **Tendência** (🚀 subindo / 📉 caindo / ➡️ estável). Sparkline por linha com `observacoes_diarias` (n_ads_ativos × dia — SVG simples inline, sem lib de chart nova). Override de status por dropdown (em_escala/saturada/pausada). Botão Biblioteca.

**FR-5 · Aba Candidatas.** Lista `status = candidata` ordenada por `atualizado_em desc`, com sparkline, delta e todos os campos de classificação. Ação: **"Copiar briefing"** — copia pro clipboard um bloco markdown com os campos da oferta (anunciante, page_id, link, nicho, funil, formato, n_ativos, dias, observações) pronto pra colar no dossiê (`Full_AIOS_LOWTICKET/inteligence/ofertas/`).

**FR-6 · Aba Infoapp.** Mesma tabela do Gate, filtrando `oportunidade_infoapp = true` em **qualquer** status exceto descartada — a fila curso→infoapp transversal.

**FR-7 · Aba Arquivo.** `status IN (descartada, saturada, pausada)` com busca por texto no anunciante e filtro por status. Somente leitura + botão Biblioteca (o cemitério é consultável, nunca editável).

**FR-8 · Estados de rede.** Loading/erro inline pt-BR (padrão do repo); mutations com `invalidateQueries`; sem state manager global.

**FR-9 · Adicionar oferta manual (no Gate).** Botão "+ Oferta manual" abre form: `page_id` **ou** link da Biblioteca (parsear `view_all_page_id` da URL), `anunciante` (opcional), `nicho`/`observacoes` (opcionais).
- Dado um `page_id` inexistente; Quando salva; Então `INSERT ofertas` com `status='alerta'`, `pais='MULTI'`, `link_ad_library` gerado pelo template do SCHEMA, e `observacoes` prefixada com `origem: manual (Board)`. A oferta entra no Gate e o Flow 1 a enriquece (n_ativos, datas) na próxima rodada de qualificação — não bloquear por campos da máquina vazios.
- Dado um `page_id` já existente; Quando salva; Então NÃO duplica: exibe aviso e abre a oferta existente no painel.

**FR-10 · Aba Rastros (CRUD do catálogo).** Tabela de `rastros` com `query, grupo, tipo_busca, funil_hint, status, populacao_observada`.
- **Adicionar:** form (query obrigatória e única, grupo, tipo_busca, funil_hint opcional) → `INSERT` com `status='a_testar'`.
- **Editar:** grupo, tipo_busca, funil_hint, populacao_observada, status inline.
- **Pausar/reativar:** toggle `status = sem_retorno` ⇄ `a_testar` (o Flow 1 ignora `sem_retorno` — é o "excluir" da doutrina). Sem delete físico.
- Badge de aviso em rastros `tipo_busca='nicho'`: "não roda no ciclo de plataforma atual" (o Flow 1 filtra `tipo_busca='plataforma'`; ciclos de nicho são evolução futura).

## 6. Aceite (E2E)

- CA-1: com o Supabase real, header mostra contagens iguais ao `select status, count(*)`.
- CA-2: analisar uma `alerta` → salvar classificação → vira `em_analise_funil` com campos persistidos no banco.
- CA-3: "Monitorar" → status `monitorando` e `data_inicio_monitoramento = hoje` no banco; a oferta aparece no Tracker e o Flow 2 (n8n) passa a snapshotá-la no dia seguinte (verificável em `observacoes_diarias`).
- CA-4: "Descartar" → some do Gate, aparece no Arquivo.
- CA-5: oferta com 7+ snapshots mostra Δ7d/tendência corretos vs `v_tracker` no SQL.
- CA-6: nenhuma ação da UI altera ofertas em `novo` nem os campos da máquina (n_ativos, datas de coleta).
- CA-7: oferta manual criada via FR-9 aparece no Gate com origem marcada; tentar criar com page_id repetido não duplica.
- CA-8: rastro adicionado na aba Rastros aparece em `select * from rastros`; rastro pausado (`sem_retorno`) não é coletado na próxima execução do Flow 1; **nenhuma tabela sofre delete físico** a partir da UI.

## 7. Tarefas (ordem de build)

- [ ] **T1** `lib/lowticket.ts` — client supabase-js + tipos TS (Oferta, TrackerRow, ObservacaoDiaria, enums) + helpers de query/mutation. Env vars no `.env`.
- [ ] **T2** Rota `/lowticket` + item na Sidebar (seção LowTicket).
- [ ] **T3** `pages/LowTicket.tsx`: header de contadores (FR-1) + esqueleto de abas.
- [ ] **T4** Aba Gate + painel de análise + mutations Monitorar/Descartar (FR-2, FR-3).
- [ ] **T5** Aba Tracker com Δ7d/tendência/sparkline + override de status (FR-4).
- [ ] **T6** Abas Candidatas (copiar briefing), Infoapp e Arquivo (FR-5..7).
- [ ] **T7** Oferta manual (FR-9) + aba Rastros com CRUD (FR-10).
- [ ] **T8** Aceite CA-1..CA-8 contra o Supabase real (já tem ~858 ofertas de dado vivo).

## 8. Fora do escopo (não construir)

Notificações; edição/exclusão de `anuncios` e `observacoes_diarias`; **delete físico em qualquer tabela**; enriquecimento LLM (agente n8n futuro); gráficos além do sparkline SVG; qualquer chamada ao FastAPI; RLS/policies (v1 aceita anon).
