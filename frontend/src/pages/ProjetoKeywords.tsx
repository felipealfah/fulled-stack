/**
 * Plano de Keywords — Gate do Board (GATE-KW-01).
 *
 * Substitui a aprovação implícita que vivia no `/seo-architect`. Aqui o Board vê
 * todas as keywords do projeto (todas as pesquisas), edita o kw_type inline,
 * seleciona linha a linha e dispara `POST /projetos/{id}/keywords/approve`.
 *
 * Sem essa aprovação explícita as keywords ficam em status='pending' e o rank
 * tracking não coleta nada — o `/seo-architect` agora aborta se sobrar pending.
 */
import { useState, useMemo, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  projetoKeywordsApi,
  projetosApi,
  type ProjetoKeyword,
  type ApprovePlanResult,
} from '../lib/api'

const KW_TYPES = [
  'PAGINA_PRINCIPAL',
  'SERVICO',
  'PAGINA_GEO',
  'LOCALIDADE',
  'SECAO',
  'SURPRESA',
  'DESCARTA',
] as const

type KwType = (typeof KW_TYPES)[number]

// Valores legados em lowercase do schema antigo → constantes canônicas
const LEGACY: Record<string, KwType> = {
  principal: 'PAGINA_PRINCIPAL',
  silo: 'SERVICO',
  geo: 'PAGINA_GEO',
  descarta: 'DESCARTA',
}

function normalizeType(raw: string | null): KwType | '' {
  if (!raw) return ''
  const up = raw.toUpperCase()
  if (raw in LEGACY) return LEGACY[raw]
  return (KW_TYPES as readonly string[]).includes(up) ? (up as KwType) : ''
}

const TYPE_CLS: Record<KwType, string> = {
  PAGINA_PRINCIPAL: 'text-emerald-400 border-emerald-500/30 bg-emerald-500/10',
  SERVICO: 'text-indigo-400 border-indigo-500/30 bg-indigo-500/10',
  PAGINA_GEO: 'text-blue-400 border-blue-500/30 bg-blue-500/10',
  LOCALIDADE: 'text-sky-400 border-sky-500/30 bg-sky-500/10',
  SECAO: 'text-amber-400 border-amber-500/30 bg-amber-500/10',
  SURPRESA: 'text-fuchsia-400 border-fuchsia-500/30 bg-fuchsia-500/10',
  DESCARTA: 'text-gray-500 border-gray-700 bg-gray-500/10',
}

const STATUS_CLS: Record<string, string> = {
  pending: 'text-amber-400 border-amber-500/30 bg-amber-500/10',
  approved: 'text-emerald-400 border-emerald-500/30 bg-emerald-500/10',
  rejected: 'text-red-400 border-red-500/30 bg-red-500/10',
}

const STATUS_LABEL: Record<string, string> = {
  pending: 'Pendente',
  approved: 'Aprovada',
  rejected: 'Rejeitada',
}

const PAGE_SIZE = 200

function Spinner() {
  return (
    <span className="inline-block w-3.5 h-3.5 border border-current border-t-transparent rounded-full animate-spin opacity-60" />
  )
}

function fmtNum(n: number | null) {
  return n === null || n === undefined ? '—' : n.toLocaleString('pt-BR')
}

function fmtBrl(n: number | null) {
  if (n === null || n === undefined) return '—'
  return `R$ ${n.toFixed(2).replace('.', ',')}`
}

export function ProjetoKeywords() {
  const { id: projetoId = '' } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  // ── filtros ──
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [tipoFilter, setTipoFilter] = useState<string>('')
  const [pesquisaFilter, setPesquisaFilter] = useState<string>('')
  const [busca, setBusca] = useState('')
  const [buscaAtiva, setBuscaAtiva] = useState('')
  const [page, setPage] = useState(0)

  // ── edições locais pendentes de envio ──
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [reclass, setReclass] = useState<Record<number, KwType>>({})
  const [saving, setSaving] = useState(false)
  const [result, setResult] = useState<ApprovePlanResult | null>(null)
  const [erro, setErro] = useState<string | null>(null)

  const filters = useMemo(
    () => ({
      status: statusFilter || undefined,
      kw_type: tipoFilter || undefined,
      pesquisa_id: pesquisaFilter || undefined,
      q: buscaAtiva || undefined,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    }),
    [statusFilter, tipoFilter, pesquisaFilter, buscaAtiva, page],
  )

  const { data: projeto } = useQuery({
    queryKey: ['projeto', projetoId],
    queryFn: () => projetosApi.get(projetoId),
    enabled: !!projetoId,
  })

  const { data, isLoading, error } = useQuery({
    queryKey: ['projeto-keywords', projetoId, filters],
    queryFn: () => projetoKeywordsApi.list(projetoId, filters),
    enabled: !!projetoId,
  })

  // useMemo para manter a identidade estável entre renders — sem isso os
  // useMemo/useCallback que dependem de `items` recalculam a cada render.
  const items = useMemo(() => data?.items ?? [], [data])
  const resumo = data?.resumo

  // Contadores globais do projeto (sem filtro) — para o cabeçalho e o CTA
  const { data: totais } = useQuery({
    queryKey: ['projeto-keywords-totais', projetoId],
    queryFn: () => projetoKeywordsApi.list(projetoId, { limit: 1 }),
    enabled: !!projetoId,
  })
  const pendingTotal = totais?.resumo.por_status.pending ?? 0
  const approvedTotal = totais?.resumo.por_status.approved ?? 0

  // Pesquisas presentes (para o filtro por serviço)
  const pesquisas = useMemo(() => {
    const map = new Map<string, { id: string; nicho: string; papel: string | null }>()
    for (const k of items) {
      if (!map.has(k.pesquisa_id)) {
        map.set(k.pesquisa_id, { id: k.pesquisa_id, nicho: k.nicho, papel: k.papel })
      }
    }
    return [...map.values()]
  }, [items])

  const effectiveType = useCallback(
    (kw: ProjetoKeyword): KwType | '' => reclass[kw.id] ?? normalizeType(kw.kw_type),
    [reclass],
  )

  const toggle = (id: number) => {
    setSelected(prev => {
      const s = new Set(prev)
      if (s.has(id)) s.delete(id)
      else s.add(id)
      return s
    })
  }

  const selectableIds = useMemo(
    () => items.filter(k => effectiveType(k) !== 'DESCARTA').map(k => k.id),
    [items, effectiveType],
  )
  const allSelected = selectableIds.length > 0 && selectableIds.every(id => selected.has(id))

  const toggleAll = () => {
    setSelected(prev => {
      const s = new Set(prev)
      if (allSelected) selectableIds.forEach(id => s.delete(id))
      else selectableIds.forEach(id => s.add(id))
      return s
    })
  }

  const setTipo = (id: number, tipo: KwType) => {
    setReclass(prev => ({ ...prev, [id]: tipo }))
    if (tipo === 'DESCARTA') {
      setSelected(prev => {
        const s = new Set(prev)
        s.delete(id)
        return s
      })
    }
  }

  const bulkSetTipo = (tipo: KwType) => {
    if (selected.size === 0) return
    setReclass(prev => {
      const next = { ...prev }
      selected.forEach(id => { next[id] = tipo })
      return next
    })
    if (tipo === 'DESCARTA') setSelected(new Set())
  }

  const reclassifyPayload = useMemo(
    () =>
      Object.entries(reclass)
        .filter(([id, tipo]) => {
          const kw = items.find(k => k.id === Number(id))
          return kw ? normalizeType(kw.kw_type) !== tipo : true
        })
        .map(([id, kw_type]) => ({ keyword_id: Number(id), kw_type })),
    [reclass, items],
  )

  const refetchAll = () => {
    queryClient.invalidateQueries({ queryKey: ['projeto-keywords', projetoId] })
    queryClient.invalidateQueries({ queryKey: ['projeto-keywords-totais', projetoId] })
  }

  const enviar = async (payload: Parameters<typeof projetoKeywordsApi.approvePlan>[1]) => {
    setSaving(true)
    setErro(null)
    setResult(null)
    try {
      const r = await projetoKeywordsApi.approvePlan(projetoId, payload)
      setResult(r)
      setSelected(new Set())
      setReclass({})
      refetchAll()
    } catch (e: unknown) {
      const detail =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setErro(detail ?? 'Falha ao salvar. Verifique a conexão com a API.')
    } finally {
      setSaving(false)
    }
  }

  const aprovarSelecionadas = () =>
    enviar({ reclassify: reclassifyPayload, approve_ids: [...selected] })

  const rejeitarSelecionadas = () =>
    enviar({ reclassify: reclassifyPayload, reject_ids: [...selected] })

  const aprovarTudo = () => {
    if (
      !confirm(
        `Aprovar TODAS as ${pendingTotal} keywords pendentes não-DESCARTA deste projeto?`,
      )
    )
      return
    enviar({ reclassify: reclassifyPayload, approve_all_non_descarta: true })
  }

  const salvarEdicoes = () => enviar({ reclassify: reclassifyPayload })

  const temEdicoes = reclassifyPayload.length > 0
  const totalPaginas = Math.ceil((data?.total ?? 0) / PAGE_SIZE)

  if (!projetoId) return null

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      {/* ── Cabeçalho ── */}
      <header className="border-b border-gray-800 px-6 py-5 sticky top-0 bg-gray-950/95 backdrop-blur z-20">
        <div className="max-w-[1600px] mx-auto">
          <button
            onClick={() => navigate(`/projetos/${projetoId}`)}
            className="text-xs font-mono text-gray-600 hover:text-gray-400 mb-2"
          >
            ← {projeto?.projeto_nome ?? 'Projeto'}
          </button>
          <div className="flex items-start justify-between gap-6 flex-wrap">
            <div>
              <h1 className="font-mono font-semibold tracking-tight text-lg">
                Plano de Keywords
              </h1>
              <p className="text-xs text-gray-600 font-mono mt-1">
                Gate do Board — nada segue para o <span className="text-gray-500">/seo-architect</span> enquanto houver pendentes
              </p>
            </div>
            <div className="flex items-center gap-3 font-mono text-xs">
              <span className="px-2.5 py-1 rounded border border-amber-500/30 bg-amber-500/10 text-amber-400">
                {pendingTotal} pendentes
              </span>
              <span className="px-2.5 py-1 rounded border border-emerald-500/30 bg-emerald-500/10 text-emerald-400">
                {approvedTotal} aprovadas
              </span>
              <button
                onClick={aprovarTudo}
                disabled={saving || pendingTotal === 0}
                className="px-3.5 py-1.5 rounded border border-emerald-500/40 bg-emerald-500/15 text-emerald-300
                           hover:bg-emerald-500/25 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                {saving ? <Spinner /> : 'Aprovar plano inteiro'}
              </button>
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-[1600px] mx-auto px-6 py-6">
        {/* ── Feedback ── */}
        {result && (
          <div className="mb-4 rounded-lg border border-emerald-500/30 bg-emerald-500/5 px-4 py-3 font-mono text-xs text-emerald-300">
            {result.approved} aprovadas · {result.rejected} rejeitadas ·{' '}
            {result.reclassified} reclassificadas · {result.skipped_descarta} DESCARTA puladas ·{' '}
            <span className={result.pending_restantes > 0 ? 'text-amber-400' : 'text-emerald-400'}>
              {result.pending_restantes} pendentes restantes
            </span>
            {result.invalid.length > 0 && (
              <div className="mt-1 text-red-400">
                {result.invalid.length} inválidas: {result.invalid[0].reason}
              </div>
            )}
          </div>
        )}
        {erro && (
          <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/5 px-4 py-3 font-mono text-xs text-red-400">
            {erro}
          </div>
        )}

        {/* ── Filtros ── */}
        <div className="flex items-center gap-2 flex-wrap mb-4 font-mono text-xs">
          <select
            value={statusFilter}
            onChange={e => { setStatusFilter(e.target.value); setPage(0) }}
            className="bg-gray-900 border border-gray-800 rounded px-2.5 py-1.5 text-gray-300"
          >
            <option value="">Todos os status</option>
            <option value="pending">Pendentes</option>
            <option value="approved">Aprovadas</option>
            <option value="rejected">Rejeitadas</option>
          </select>

          <select
            value={tipoFilter}
            onChange={e => { setTipoFilter(e.target.value); setPage(0) }}
            className="bg-gray-900 border border-gray-800 rounded px-2.5 py-1.5 text-gray-300"
          >
            <option value="">Todos os tipos</option>
            <option value="!DESCARTA">Exceto DESCARTA</option>
            {KW_TYPES.map(t => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>

          {pesquisas.length > 1 && (
            <select
              value={pesquisaFilter}
              onChange={e => { setPesquisaFilter(e.target.value); setPage(0) }}
              className="bg-gray-900 border border-gray-800 rounded px-2.5 py-1.5 text-gray-300"
            >
              <option value="">Todos os serviços</option>
              {pesquisas.map(p => (
                <option key={p.id} value={p.id}>
                  {p.nicho}{p.papel ? ` (${p.papel})` : ''}
                </option>
              ))}
            </select>
          )}

          <form
            onSubmit={e => { e.preventDefault(); setBuscaAtiva(busca); setPage(0) }}
            className="flex items-center gap-1.5"
          >
            <input
              value={busca}
              onChange={e => setBusca(e.target.value)}
              placeholder="buscar keyword..."
              className="bg-gray-900 border border-gray-800 rounded px-2.5 py-1.5 text-gray-300 w-52
                         placeholder:text-gray-700 focus:outline-none focus:border-gray-700"
            />
            <button type="submit" className="px-2.5 py-1.5 rounded border border-gray-800 bg-gray-900 text-gray-400 hover:text-gray-200">
              buscar
            </button>
          </form>

          <span className="ml-auto text-gray-600">
            {data?.total ?? 0} keyword{(data?.total ?? 0) !== 1 ? 's' : ''} no filtro
            {resumo && Object.keys(resumo.por_status).length > 0 && (
              <> · {Object.entries(resumo.por_status).map(([s, n]) => `${STATUS_LABEL[s] ?? s}: ${n}`).join(' · ')}</>
            )}
          </span>
        </div>

        {/* ── Barra de ações em lote ── */}
        {(selected.size > 0 || temEdicoes) && (
          <div className="sticky top-[105px] z-10 mb-3 flex items-center gap-2 flex-wrap
                          rounded-lg border border-gray-800 bg-gray-900/95 backdrop-blur px-4 py-2.5 font-mono text-xs">
            <span className="text-gray-400">
              {selected.size} selecionada{selected.size !== 1 ? 's' : ''}
              {temEdicoes && <span className="text-amber-400"> · {reclassifyPayload.length} edição(ões) não salva(s)</span>}
            </span>

            <div className="flex items-center gap-1.5 ml-2">
              <span className="text-gray-700">reclassificar para:</span>
              {KW_TYPES.map(t => (
                <button
                  key={t}
                  onClick={() => bulkSetTipo(t)}
                  disabled={selected.size === 0}
                  className={`px-2 py-1 rounded border transition-colors disabled:opacity-30 ${TYPE_CLS[t]}`}
                >
                  {t}
                </button>
              ))}
            </div>

            <div className="ml-auto flex items-center gap-2">
              {temEdicoes && (
                <button
                  onClick={salvarEdicoes}
                  disabled={saving}
                  className="px-3 py-1.5 rounded border border-gray-700 bg-gray-800 text-gray-300 hover:bg-gray-700 disabled:opacity-40"
                >
                  Salvar edições
                </button>
              )}
              <button
                onClick={rejeitarSelecionadas}
                disabled={saving || selected.size === 0}
                className="px-3 py-1.5 rounded border border-red-500/40 bg-red-500/10 text-red-400
                           hover:bg-red-500/20 disabled:opacity-40"
              >
                Rejeitar
              </button>
              <button
                onClick={aprovarSelecionadas}
                disabled={saving || selected.size === 0}
                className="px-3 py-1.5 rounded border border-emerald-500/40 bg-emerald-500/15 text-emerald-300
                           hover:bg-emerald-500/25 disabled:opacity-40"
              >
                {saving ? <Spinner /> : `Aprovar ${selected.size}`}
              </button>
            </div>
          </div>
        )}

        {/* ── Tabela ── */}
        {isLoading ? (
          <div className="py-16 text-center text-gray-600 font-mono text-sm flex items-center justify-center gap-2">
            <Spinner /> Carregando keywords...
          </div>
        ) : error ? (
          <p className="py-16 text-center text-red-400 font-mono text-sm">
            Erro ao carregar keywords do projeto.
          </p>
        ) : items.length === 0 ? (
          <p className="py-16 text-center text-gray-600 font-mono text-sm">
            Nenhuma keyword para este filtro.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-gray-800">
            <table className="w-full font-mono text-xs">
              <thead className="bg-gray-900 text-gray-600">
                <tr>
                  <th className="px-3 py-2.5 w-10 text-left">
                    <input
                      type="checkbox"
                      checked={allSelected}
                      onChange={toggleAll}
                      className="accent-emerald-500"
                      title="Selecionar todas (exceto DESCARTA)"
                    />
                  </th>
                  <th className="px-3 py-2.5 text-left font-medium">Keyword</th>
                  <th className="px-3 py-2.5 text-left font-medium w-44">Tipo</th>
                  <th className="px-3 py-2.5 text-left font-medium w-24">Status</th>
                  <th className="px-3 py-2.5 text-right font-medium w-20">Vol/mês</th>
                  <th className="px-3 py-2.5 text-right font-medium w-24">Pos 1–4</th>
                  <th className="px-3 py-2.5 text-right font-medium w-20">Dific.</th>
                  <th className="px-3 py-2.5 text-left font-medium w-32">Serviço</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/70">
                {items.map(kw => {
                  const tipo = effectiveType(kw)
                  const editado = reclass[kw.id] !== undefined && reclass[kw.id] !== normalizeType(kw.kw_type)
                  const isSel = selected.has(kw.id)
                  return (
                    <tr
                      key={kw.id}
                      className={`transition-colors ${isSel ? 'bg-emerald-500/5' : 'hover:bg-gray-900/50'}`}
                    >
                      <td className="px-3 py-2">
                        <input
                          type="checkbox"
                          checked={isSel}
                          disabled={tipo === 'DESCARTA'}
                          onChange={() => toggle(kw.id)}
                          className="accent-emerald-500 disabled:opacity-30"
                        />
                      </td>
                      <td className="px-3 py-2 text-gray-200">
                        {kw.keyword}
                        {editado && <span className="ml-2 text-[10px] text-amber-400">editada</span>}
                      </td>
                      <td className="px-3 py-2">
                        <select
                          value={tipo}
                          onChange={e => setTipo(kw.id, e.target.value as KwType)}
                          className={`rounded border px-1.5 py-1 bg-gray-950 ${tipo ? TYPE_CLS[tipo] : 'text-gray-500 border-gray-800'}`}
                        >
                          {!tipo && <option value="">— sem tipo —</option>}
                          {KW_TYPES.map(t => (
                            <option key={t} value={t} className="bg-gray-900 text-gray-200">{t}</option>
                          ))}
                        </select>
                      </td>
                      <td className="px-3 py-2">
                        <span className={`px-2 py-0.5 rounded border ${STATUS_CLS[kw.status] ?? 'text-gray-500 border-gray-700'}`}>
                          {STATUS_LABEL[kw.status] ?? kw.status}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right text-gray-400">{fmtNum(kw.avg_monthly_searches)}</td>
                      <td className="px-3 py-2 text-right text-gray-400">{fmtBrl(kw.bid_pos1_4_brl)}</td>
                      <td className="px-3 py-2 text-right text-gray-500">{kw.difficulty_label ?? '—'}</td>
                      <td className="px-3 py-2 text-gray-600 truncate max-w-[8rem]" title={kw.nicho}>
                        {kw.nicho}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* ── Paginação ── */}
        {totalPaginas > 1 && (
          <div className="flex items-center justify-center gap-3 mt-4 font-mono text-xs">
            <button
              onClick={() => setPage(p => Math.max(0, p - 1))}
              disabled={page === 0}
              className="px-3 py-1.5 rounded border border-gray-800 bg-gray-900 text-gray-400 disabled:opacity-30"
            >
              ← anterior
            </button>
            <span className="text-gray-600">
              página {page + 1} de {totalPaginas}
            </span>
            <button
              onClick={() => setPage(p => Math.min(totalPaginas - 1, p + 1))}
              disabled={page >= totalPaginas - 1}
              className="px-3 py-1.5 rounded border border-gray-800 bg-gray-900 text-gray-400 disabled:opacity-30"
            >
              próxima →
            </button>
          </div>
        )}
      </main>
    </div>
  )
}
