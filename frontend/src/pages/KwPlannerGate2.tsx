import { useState, useEffect, useCallback, useMemo } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { pesquisasApi, projetosApi, type Pesquisa, type Keyword, type Projeto } from '../lib/api'

// ─── Types e configuração ─────────────────────────────────────────
type KwType = 'PAGINA_PRINCIPAL' | 'SERVICO' | 'PAGINA_GEO' | 'SECAO' | 'DESCARTA'
type View = { type: 'list' } | { type: 'scorecard'; pesquisaId: string }

const STATUS_CFG = {
  classificado: { label: 'Aguardando revisão', cls: 'bg-amber-500/10 text-amber-400 border border-amber-500/25' },
  aprovado:     { label: 'Aprovado',            cls: 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/25' },
} as const

// Mapeia valores legados do banco para o formato novo
const NORMALIZE_KW_TYPE: Record<string, KwType> = {
  principal: 'PAGINA_PRINCIPAL',
  silo:      'SERVICO',
  geo:       'PAGINA_GEO',
  descarta:  'DESCARTA',
}
function normalizeKwType(raw: string | null | undefined): KwType | null {
  if (!raw) return null
  if (raw in NORMALIZE_KW_TYPE) return NORMALIZE_KW_TYPE[raw]
  return raw as KwType
}

const KW_TYPE_CYCLE: KwType[] = ['PAGINA_PRINCIPAL', 'SERVICO', 'PAGINA_GEO', 'SECAO', 'DESCARTA']

const KW_TYPE_CFG: Record<KwType, { label: string; cls: string; borderCls: string; accentCls: string }> = {
  PAGINA_PRINCIPAL: {
    label: '🏠 Página Principal',
    cls: 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/20',
    borderCls: 'border-emerald-500/40',
    accentCls: 'border-emerald-500/40',
  },
  SERVICO: {
    label: '🔧 Serviços',
    cls: 'bg-indigo-500/10 text-indigo-400 border border-indigo-500/30 hover:bg-indigo-500/20',
    borderCls: 'border-indigo-500/40',
    accentCls: 'border-indigo-500/40',
  },
  PAGINA_GEO: {
    label: '📍 Páginas Geo',
    cls: 'bg-blue-500/10 text-blue-400 border border-blue-500/30 hover:bg-blue-500/20',
    borderCls: 'border-blue-500/40',
    accentCls: 'border-blue-500/40',
  },
  SECAO: {
    label: '📄 Seções',
    cls: 'bg-amber-500/10 text-amber-400 border border-amber-500/30 hover:bg-amber-500/20',
    borderCls: 'border-amber-500/40',
    accentCls: 'border-amber-500/40',
  },
  DESCARTA: {
    label: '🗑️ Descartadas',
    cls: 'bg-gray-500/10 text-gray-500 border border-gray-700 hover:bg-gray-500/20',
    borderCls: 'border-gray-700',
    accentCls: 'border-gray-700',
  },
}

// ─── Icons ────────────────────────────────────────────────────────
function CheckIcon() {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
    </svg>
  )
}

function Spinner({ size = 'sm' }: { size?: 'sm' | 'md' }) {
  const cls = size === 'sm' ? 'w-3.5 h-3.5' : 'w-5 h-5'
  return (
    <span className={`inline-block ${cls} border border-current border-t-transparent rounded-full animate-spin opacity-60`} />
  )
}

// ─── TrashIcon ────────────────────────────────────────────────────
function TrashIcon() {
  return (
    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
    </svg>
  )
}

// ─── Gate2PesquisaList ────────────────────────────────────────────
function Gate2PesquisaList({ onSelect }: { onSelect: (id: string) => void }) {
  const queryClient = useQueryClient()
  const [deletingId, setDeletingId] = useState<string | null>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['pesquisas-gate2'],
    queryFn: pesquisasApi.listGate2,
  })

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation()
    if (!confirm('Excluir esta pesquisa e todas as suas keywords?')) return
    setDeletingId(id)
    try {
      await pesquisasApi.deletePesquisa(id)
      queryClient.invalidateQueries({ queryKey: ['pesquisas-gate2'] })
    } catch {
      // silent
    } finally {
      setDeletingId(null)
    }
  }

  if (isLoading) return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center">
      <div className="flex items-center gap-2.5 text-gray-600 text-sm font-mono">
        <Spinner size="md" /> Carregando pesquisas...
      </div>
    </div>
  )

  if (error) return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center">
      <p className="text-red-400 text-sm font-mono">Erro ao carregar pesquisas. Verifique a conexão com a API.</p>
    </div>
  )

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      <header className="border-b border-gray-800 px-6 py-5">
        <div className="max-w-3xl mx-auto flex items-center gap-3">
          <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse shrink-0" />
          <div>
            <h1 className="font-mono font-semibold tracking-tight text-gray-100">Kw Planner</h1>
            <p className="text-xs text-gray-600 font-mono mt-0.5">Revisão de keywords classificadas pelo agente</p>
          </div>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-8">
        {(!data || data.length === 0) ? (
          <div className="flex flex-col items-center gap-4 py-16 text-center">
            <h2 className="font-mono font-semibold text-gray-400">Nenhuma pesquisa aguardando revisão</h2>
            <p className="font-mono text-sm text-gray-600 max-w-sm">
              O agente kw_validator classifica as keywords automaticamente. Aguarde a conclusão do agente.
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {data.map((p: Pesquisa) => {
              const s = STATUS_CFG[p.status as keyof typeof STATUS_CFG] ?? STATUS_CFG.classificado
              return (
                <div key={p.id} className="relative group">
                  <button
                    onClick={() => onSelect(p.id)}
                    className="w-full text-left bg-gray-900 border border-gray-800 rounded-lg px-5 py-4 hover:border-gray-700 hover:bg-gray-800/60 transition-all duration-150"
                  >
                    <div className="flex items-center justify-between gap-3 pr-8">
                      <div className="min-w-0">
                        <span className="font-mono font-semibold text-gray-100 group-hover:text-white">
                          {p.projeto_nome}
                        </span>
                        <span className="text-gray-600 text-sm font-mono ml-2">{p.nicho} · {p.cidade}</span>
                      </div>
                      <span className={`text-xs font-mono px-2 py-0.5 rounded-full whitespace-nowrap ${s.cls}`}>
                        {s.label}
                      </span>
                    </div>
                    <div className="flex items-center gap-3 mt-2 text-xs font-mono text-gray-700">
                      {p.total_keywords != null && <span>{p.total_keywords} keywords</span>}
                      <span>{new Date(p.created_at).toLocaleDateString('pt-BR')}</span>
                    </div>
                  </button>
                  <button
                    onClick={e => handleDelete(e, p.id)}
                    disabled={deletingId === p.id}
                    className="absolute right-3 top-1/2 -translate-y-1/2 p-1.5 rounded text-gray-700 hover:text-red-400 hover:bg-red-500/10 opacity-0 group-hover:opacity-100 transition-all disabled:opacity-50"
                    title="Excluir pesquisa"
                  >
                    {deletingId === p.id ? <Spinner /> : <TrashIcon />}
                  </button>
                </div>
              )
            })}
          </div>
        )}
      </main>
    </div>
  )
}

// ─── KeywordNoteCell ──────────────────────────────────────────────
interface NoteCellProps {
  kw: Keyword
  onUpdate: (id: number, patch: Partial<Keyword>) => void
  accentCls: string
}

function KeywordNoteCell({ kw, onUpdate, accentCls }: NoteCellProps) {
  const [editingNote, setEditingNote] = useState(false)
  const [noteText, setNoteText] = useState(kw.board_note ?? '')

  useEffect(() => { setNoteText(kw.board_note ?? '') }, [kw.board_note])

  return (
    <div className={`border-l-2 ${accentCls} pl-2`}>
      {editingNote ? (
        <textarea
          autoFocus
          value={noteText}
          onChange={e => setNoteText(e.target.value)}
          onBlur={() => {
            setEditingNote(false)
            if (noteText !== (kw.board_note ?? '')) {
              onUpdate(kw.id, { board_note: noteText || null as unknown as string })
            }
          }}
          rows={2}
          placeholder="Adicionar nota..."
          className="w-full bg-transparent font-mono text-xs text-gray-300 focus:outline-none resize-none placeholder-gray-700 border-b border-emerald-400"
        />
      ) : (
        <p
          onClick={() => setEditingNote(true)}
          className="font-mono text-xs text-gray-400 cursor-text hover:text-gray-200 transition-colors min-h-[1.5rem]"
          title="Clique para editar"
        >
          {noteText || <span className="text-gray-700 italic">Sem nota — clique para adicionar</span>}
        </p>
      )}
    </div>
  )
}

// ─── Gate2Scorecard ───────────────────────────────────────────────
function Gate2Scorecard({ pesquisaId, onBack }: { pesquisaId: string; onBack: () => void }) {
  const queryClient = useQueryClient()
  const [keywords, setKeywords] = useState<Keyword[]>([])
  const [approving, setApproving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [rejecting, setRejecting] = useState(false)
  const [showApprovedModal, setShowApprovedModal] = useState(false)
  const [projetoMode, setProjetoMode] = useState<'none' | 'new' | 'existing'>('none')
  const [selectedProjetoId, setSelectedProjetoId] = useState<string | null>(null)
  const [projetoResult, setProjetoResult] = useState<{ id: string } | null>(null)
  const [showUnapproved, setShowUnapproved] = useState(false)
  const [includingKwTypes, setIncludingKwTypes] = useState<Record<number, KwType>>({})
  const [includingIds, setIncludingIds] = useState<Set<number>>(new Set())

  const { data, isLoading, error } = useQuery({
    queryKey: ['pesquisa-gate2', pesquisaId],
    queryFn: () => pesquisasApi.get(pesquisaId),
  })

  const { data: projetos } = useQuery({
    queryKey: ['projetos'],
    queryFn: () => projetosApi.list(),
    enabled: projetoMode === 'existing',
  })

  useEffect(() => {
    if (data?.keywords) setKeywords(data.keywords)
  }, [data])

  // Agrupamento por kw_type (sempre na ordem fixa, normaliza valores legados)
  const grouped = useMemo(() => {
    const order: KwType[] = ['PAGINA_PRINCIPAL', 'SERVICO', 'PAGINA_GEO', 'SECAO', 'DESCARTA']
    return order.map(tipo => ({
      tipo,
      keywords: keywords.filter(k => normalizeKwType(k.kw_type) === tipo),
    }))
  }, [keywords])

  const countByType = useCallback((tipo: KwType) =>
    keywords.filter(k => normalizeKwType(k.kw_type) === tipo).length, [keywords])

  const handleUpdate = useCallback(async (id: number, patch: Partial<Keyword>) => {
    setKeywords(prev => prev.map(k => k.id === id ? { ...k, ...patch } : k))
    try {
      await pesquisasApi.updateKeyword(pesquisaId, id, patch)
    } catch {
      const original = data?.keywords.find(k => k.id === id)
      if (original) setKeywords(prev => prev.map(k => k.id === id ? { ...k, ...original } : k))
    }
  }, [pesquisaId, data])

  const handleApproveGate2 = async () => {
    setApproving(true)
    try {
      const opts = projetoMode === 'new'
        ? { criar_projeto: true }
        : projetoMode === 'existing' && selectedProjetoId
          ? { projeto_id: selectedProjetoId }
          : {}
      const result = await pesquisasApi.approveGate2(pesquisaId, opts)
      if (result.projeto_id) setProjetoResult({ id: result.projeto_id })
      setShowApprovedModal(true)
      queryClient.invalidateQueries({ queryKey: ['pesquisas-gate2'] })
    } catch {
      // sem toast — consistente com Gate 1
    } finally {
      setApproving(false)
    }
  }

  const handleDelete = async () => {
    if (!confirm('Excluir esta pesquisa e todas as suas keywords?')) return
    setDeleting(true)
    try {
      await pesquisasApi.deletePesquisa(pesquisaId)
      queryClient.invalidateQueries({ queryKey: ['pesquisas-gate2'] })
      onBack()
    } catch {
      // silent
    } finally {
      setDeleting(false)
    }
  }

  const handleReject = async () => {
    if (!confirm('Reprovar esta pesquisa? As keywords serão removidas.')) return
    setRejecting(true)
    try {
      await pesquisasApi.reject(pesquisaId)
      queryClient.invalidateQueries({ queryKey: ['pesquisas-gate2'] })
      onBack()
    } catch {
      // silent
    } finally {
      setRejecting(false)
    }
  }

  const handleInclude = async (kwId: number) => {
    const kwType = includingKwTypes[kwId] ?? 'SECAO'
    setIncludingIds(prev => new Set(prev).add(kwId))
    try {
      await pesquisasApi.updateKeyword(pesquisaId, kwId, { status: 'approved', kw_type: kwType })
      setKeywords(prev => prev.map(k => k.id === kwId ? { ...k, status: 'approved', kw_type: kwType } : k))
    } catch {
      // silent
    } finally {
      setIncludingIds(prev => { const s = new Set(prev); s.delete(kwId); return s })
    }
  }

  // ── estados de carregamento ──
  if (isLoading) return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center">
      <div className="flex items-center gap-2.5 text-gray-600 text-sm font-mono">
        <Spinner size="md" /> Carregando...
      </div>
    </div>
  )

  if (error || !data) return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center">
      <p className="text-red-400 text-sm font-mono">Erro ao carregar pesquisa. Tente recarregar a página.</p>
    </div>
  )

  const { pesquisa } = data

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 pb-24">

      {/* Header sticky */}
      <header className="sticky top-0 z-10 bg-gray-950/95 backdrop-blur border-b border-gray-800 px-6 py-3.5">
        <div className="max-w-6xl mx-auto flex items-center gap-4">
          <button
            onClick={onBack}
            className="font-mono text-sm text-gray-600 hover:text-gray-300 transition-colors"
          >
            ← voltar
          </button>
          <div className="h-4 w-px bg-gray-800" />
          <div className="min-w-0 flex-1">
            <span className="font-mono font-semibold text-gray-100">{pesquisa.projeto_nome}</span>
            <span className="text-gray-600 text-xs font-mono ml-2">{pesquisa.nicho} · {pesquisa.cidade}</span>
            <button
              onClick={() => navigator.clipboard.writeText(pesquisaId)}
              className="ml-3 font-mono text-xs text-gray-700 hover:text-gray-400 transition-colors cursor-pointer"
              title="Clique para copiar pesquisa_id"
            >
              {pesquisaId}
            </button>
          </div>
          <div className="flex items-center gap-3 text-xs font-mono shrink-0">
            <span className="text-gray-600">{keywords.length} total</span>
            <span className="text-emerald-400">{countByType('PAGINA_PRINCIPAL')} P</span>
            <span className="text-indigo-400">{countByType('SERVICO')} Sv</span>
            <span className="text-blue-400">{countByType('PAGINA_GEO')} G</span>
            <span className="text-amber-400">{countByType('SECAO')} S</span>
            <span className="text-gray-500">{countByType('DESCARTA')} D</span>
          </div>
        </div>
      </header>

      {/* Grupos de keywords */}
      <main className="max-w-6xl mx-auto px-6 py-6 space-y-8">
        {grouped.map(({ tipo, keywords: kwGroup }) => {
          const cfg = KW_TYPE_CFG[tipo]
          return (
            <section key={tipo}>
              {/* Header do grupo */}
              <div className={`flex items-center gap-2 pb-2 border-b-2 ${cfg.borderCls} mb-3`}>
                <span className={`text-xs font-mono font-semibold uppercase tracking-wider px-2.5 py-1 rounded ${cfg.cls}`}>
                  {cfg.label}
                </span>
                <span className="text-xs font-mono text-gray-600">
                  {kwGroup.length} keyword{kwGroup.length !== 1 ? 's' : ''}
                </span>
              </div>

              {/* Tabela do grupo */}
              <div className="rounded-lg border border-gray-800 overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-gray-800 bg-gray-900/80">
                      <th className="px-3 py-3 text-left">
                        <span className="text-xs font-mono font-semibold uppercase tracking-wider text-gray-600">
                          Keyword
                        </span>
                      </th>
                      <th className="px-3 py-3 text-right w-24">
                        <span className="text-xs font-mono font-semibold uppercase tracking-wider text-gray-600">
                          Vol/mês
                        </span>
                      </th>
                      <th className="px-3 py-3 text-right w-24">
                        <span className="text-xs font-mono font-semibold uppercase tracking-wider text-gray-600">
                          CPC
                        </span>
                      </th>
                      <th className="px-3 py-3 text-right w-16">
                        <span className="text-xs font-mono font-semibold uppercase tracking-wider text-gray-600">
                          Score
                        </span>
                      </th>
                      <th className="px-3 py-3 text-center w-24">
                        <span className="text-xs font-mono font-semibold uppercase tracking-wider text-gray-600">
                          Dific.
                        </span>
                      </th>
                      <th className="px-3 py-3 text-left">
                        <span className="text-xs font-mono font-semibold uppercase tracking-wider text-gray-600">
                          Top Concorrente
                        </span>
                      </th>
                      <th className="px-3 py-3 text-left">
                        <span className="text-xs font-mono font-semibold uppercase tracking-wider text-gray-600">
                          Nota do Board
                        </span>
                      </th>
                      <th className="px-3 py-3 text-center w-36">
                        <span className="text-xs font-mono font-semibold uppercase tracking-wider text-gray-600">
                          Tipo
                        </span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {kwGroup.length === 0 ? (
                      <tr>
                        <td colSpan={8} className="px-4 py-6 text-center">
                          <span className="font-mono text-xs text-gray-700 italic">
                            Nenhuma keyword classificada como {tipo}
                          </span>
                        </td>
                      </tr>
                    ) : (
                      kwGroup.map(kw => (
                        <tr key={kw.id} className="border-b border-gray-800/40 hover:bg-gray-800/20">
                          {/* Keyword */}
                          <td className="px-3 py-2">
                            <span className="font-mono text-sm text-gray-200">{kw.keyword}</span>
                          </td>

                          {/* Volume */}
                          <td className="px-3 py-2 text-right w-24">
                            <span className="font-mono text-xs text-gray-500">
                              {kw.avg_monthly_searches?.toLocaleString('pt-BR') ?? '—'}
                            </span>
                          </td>

                          {/* CPC */}
                          <td className="px-3 py-2 text-right w-24">
                            <span className="font-mono text-xs text-gray-500">
                              {kw.bid_pos1_4_brl != null ? `R$ ${kw.bid_pos1_4_brl.toFixed(2)}` : '—'}
                            </span>
                          </td>

                          {/* competitive_score */}
                          <td className="px-3 py-2 text-right w-16">
                            {kw.competitive_score != null ? (
                              <span className={`font-mono text-xs font-semibold ${
                                kw.competitive_score >= 67 ? 'text-red-400' :
                                kw.competitive_score >= 34 ? 'text-amber-400' : 'text-emerald-400'
                              }`}>
                                {kw.competitive_score}
                              </span>
                            ) : (
                              <span className="font-mono text-xs text-gray-700">—</span>
                            )}
                          </td>

                          {/* difficulty_label */}
                          <td className="px-3 py-2 text-center w-24">
                            {kw.difficulty_label != null ? (
                              <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded border ${
                                kw.difficulty_label === 'alto' || kw.difficulty_label === 'alta' || kw.difficulty_label === 'muito_alta'
                                  ? 'bg-red-500/10 text-red-400 border-red-500/30'
                                  : kw.difficulty_label === 'médio' || kw.difficulty_label === 'media'
                                  ? 'bg-amber-500/10 text-amber-400 border-amber-500/30'
                                  : 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                              }`}>
                                {kw.difficulty_label}
                              </span>
                            ) : (
                              <span className="font-mono text-xs text-gray-700">—</span>
                            )}
                          </td>

                          {/* top_competitor_url */}
                          <td className="px-3 py-2 max-w-[180px]">
                            {kw.top_competitor_url ? (
                              <a
                                href={kw.top_competitor_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="font-mono text-[11px] text-blue-400 hover:text-blue-300 truncate block"
                                title={kw.top_competitor_url}
                              >
                                {new URL(kw.top_competitor_url).hostname.replace('www.', '')}
                              </a>
                            ) : (
                              <span className="font-mono text-xs text-gray-700">—</span>
                            )}
                          </td>

                          {/* board_note (inline edit) */}
                          <td className="px-3 py-2">
                            <KeywordNoteCell
                              kw={kw}
                              onUpdate={handleUpdate}
                              accentCls={cfg.accentCls}
                            />
                          </td>

                          {/* kw_type select */}
                          <td className="px-3 py-2 w-44">
                            <select
                              value={kw.kw_type ?? ''}
                              onChange={e => handleUpdate(kw.id, { kw_type: e.target.value as KwType })}
                              className={`w-full text-xs font-mono px-2 py-0.5 rounded border bg-gray-950 outline-none cursor-pointer transition-all duration-150 ${
                                kw.kw_type && KW_TYPE_CFG[kw.kw_type as KwType]
                                  ? KW_TYPE_CFG[kw.kw_type as KwType].cls
                                  : 'text-gray-500 border-gray-800'
                              }`}
                            >
                              {KW_TYPE_CYCLE.map(t => (
                                <option key={t} value={t} className="bg-gray-900 text-gray-100">
                                  {t}
                                </option>
                              ))}
                            </select>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </section>
          )
        })}

        {/* Painel: keywords não incluídas */}
        {(() => {
          const unapproved = keywords.filter(k => k.status !== 'approved')
          if (unapproved.length === 0) return null
          return (
            <section className="mt-4">
              <button
                onClick={() => setShowUnapproved(v => !v)}
                className="flex items-center gap-2 text-xs font-mono text-gray-600 hover:text-gray-400 transition-colors mb-3"
              >
                <span className={`transition-transform ${showUnapproved ? 'rotate-90' : ''}`}>▶</span>
                {unapproved.length} keyword{unapproved.length !== 1 ? 's' : ''} não incluída{unapproved.length !== 1 ? 's' : ''} (ficaram fora no Gate 1)
              </button>

              {showUnapproved && (
                <div className="rounded-lg border border-gray-800 overflow-x-auto">
                  <table className="w-full">
                    <thead>
                      <tr className="border-b border-gray-800 bg-gray-900/80">
                        <th className="px-3 py-3 text-left"><span className="text-xs font-mono font-semibold uppercase tracking-wider text-gray-600">Keyword</span></th>
                        <th className="px-3 py-3 text-center w-20"><span className="text-xs font-mono font-semibold uppercase tracking-wider text-gray-600">GO/NO-GO</span></th>
                        <th className="px-3 py-3 text-right w-24"><span className="text-xs font-mono font-semibold uppercase tracking-wider text-gray-600">Vol/mês</span></th>
                        <th className="px-3 py-3 text-right w-24"><span className="text-xs font-mono font-semibold uppercase tracking-wider text-gray-600">CPC</span></th>
                        <th className="px-3 py-3 text-center w-44"><span className="text-xs font-mono font-semibold uppercase tracking-wider text-gray-600">Tipo</span></th>
                        <th className="px-3 py-3 w-24"></th>
                      </tr>
                    </thead>
                    <tbody>
                      {unapproved.map(kw => (
                        <tr key={kw.id} className="border-b border-gray-800/40 hover:bg-gray-800/20">
                          <td className="px-3 py-2">
                            <span className="font-mono text-sm text-gray-400">{kw.keyword}</span>
                          </td>
                          <td className="px-3 py-2 text-center">
                            <span className={`text-xs font-mono ${kw.go_nogo === 'GO' ? 'text-emerald-400' : 'text-red-400'}`}>
                              {kw.go_nogo ?? '—'}
                            </span>
                          </td>
                          <td className="px-3 py-2 text-right">
                            <span className="font-mono text-xs text-gray-500">
                              {kw.avg_monthly_searches?.toLocaleString('pt-BR') ?? '—'}
                            </span>
                          </td>
                          <td className="px-3 py-2 text-right">
                            <span className="font-mono text-xs text-gray-500">
                              {kw.bid_pos1_4_brl != null ? `R$ ${kw.bid_pos1_4_brl.toFixed(2)}` : '—'}
                            </span>
                          </td>
                          <td className="px-3 py-2">
                            <select
                              value={includingKwTypes[kw.id] ?? 'SECAO'}
                              onChange={e => setIncludingKwTypes(prev => ({ ...prev, [kw.id]: e.target.value as KwType }))}
                              className="w-full text-xs font-mono px-2 py-0.5 rounded border bg-gray-950 text-gray-400 border-gray-700 outline-none"
                            >
                              {KW_TYPE_CYCLE.map(t => (
                                <option key={t} value={t} className="bg-gray-900 text-gray-100">{t}</option>
                              ))}
                            </select>
                          </td>
                          <td className="px-3 py-2 text-center">
                            <button
                              onClick={() => handleInclude(kw.id)}
                              disabled={includingIds.has(kw.id)}
                              className="text-xs font-mono px-2.5 py-1 rounded border border-emerald-500/40 text-emerald-400 hover:bg-emerald-500/10 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
                            >
                              {includingIds.has(kw.id) ? <Spinner /> : 'Incluir'}
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          )
        })()}
      </main>

      {/* Sticky action bar */}
      <div className="fixed bottom-0 left-0 right-0 z-20 border-t border-gray-800 bg-gray-950/90 backdrop-blur px-6 py-3.5">
        <div className="max-w-6xl mx-auto flex flex-col gap-3">

          {/* Vinculação de projeto — sempre visível */}
          <div className="flex items-center gap-3 pt-1">
            <span className="text-xs font-mono text-gray-600 shrink-0">
              {pesquisa.status === 'aprovado' ? 'Projeto vinculado:' : 'Vincular a projeto:'}
            </span>
            <div className="flex items-center gap-2">
              {(['none', 'new', 'existing'] as const).map(mode => (
                <button
                  key={mode}
                  onClick={() => { setProjetoMode(mode); setSelectedProjetoId(null) }}
                  className={`text-xs font-mono px-2.5 py-1 rounded border transition-all ${
                    projetoMode === mode
                      ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/40'
                      : 'text-gray-500 border-gray-800 hover:text-gray-300 hover:border-gray-700'
                  }`}
                >
                  {mode === 'none' ? 'Não vincular' : mode === 'new' ? '+ Criar projeto' : 'Projeto existente'}
                </button>
              ))}
            </div>
            {projetoMode === 'existing' && (
              <select
                value={selectedProjetoId ?? ''}
                onChange={e => setSelectedProjetoId(e.target.value || null)}
                className="text-xs font-mono bg-gray-900 border border-gray-700 text-gray-300 rounded px-2 py-1 outline-none"
              >
                <option value="">Selecione...</option>
                {(projetos as Projeto[] ?? []).map(p => (
                  <option key={p.id} value={p.id}>{p.projeto_nome} — {p.nicho}</option>
                ))}
              </select>
            )}
          </div>

          <div className="flex items-center justify-between gap-4">
            {/* Resumo + ações destrutivas */}
            <div className="flex items-center gap-4">
              <span className="text-sm font-mono text-gray-600">
                {keywords.length} kw —{' '}
                <span className="text-emerald-400">{countByType('PAGINA_PRINCIPAL')}P</span>
                {' · '}
                <span className="text-indigo-400">{countByType('SERVICO')}Sv</span>
                {' · '}
                <span className="text-blue-400">{countByType('PAGINA_GEO')}G</span>
                {' · '}
                <span className="text-amber-400">{countByType('SECAO')}S</span>
                {' · '}
                <span className="text-gray-500">{countByType('DESCARTA')}D</span>
              </span>
              <div className="flex items-center gap-2">
                <button
                  onClick={handleReject}
                  disabled={rejecting || deleting}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-mono text-amber-500 border border-amber-500/30 rounded hover:bg-amber-500/10 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
                >
                  {rejecting ? <Spinner /> : null} Reprovar
                </button>
                <button
                  onClick={handleDelete}
                  disabled={deleting || rejecting}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-mono text-red-500 border border-red-500/30 rounded hover:bg-red-500/10 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
                >
                  {deleting ? <Spinner /> : <TrashIcon />} Excluir
                </button>
              </div>
            </div>

            {/* Ação principal — condicional por status */}
            {pesquisa.status === 'aprovado' ? (
              <div className="flex items-center gap-3">
                <span className="text-xs font-mono text-emerald-500 border border-emerald-500/30 px-3 py-1.5 rounded bg-emerald-500/10">
                  ✓ Aprovado
                </span>
                {(projetoMode !== 'none') && (
                  <button
                    onClick={handleApproveGate2}
                    disabled={approving || (projetoMode === 'existing' && !selectedProjetoId)}
                    className="flex items-center gap-2 px-4 py-2 text-sm font-mono bg-emerald-600 text-white rounded-lg hover:bg-emerald-500 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
                  >
                    {approving ? <><Spinner /> Salvando...</> : 'Atualizar vinculação →'}
                  </button>
                )}
              </div>
            ) : (
              <button
                onClick={handleApproveGate2}
                disabled={approving || (projetoMode === 'existing' && !selectedProjetoId)}
                className="flex items-center gap-2 px-4 py-2 text-sm font-mono bg-emerald-600 text-white rounded-lg hover:bg-emerald-500 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
              >
                {approving ? <><Spinner /> Aprovando...</> : 'Aprovar arquitetura →'}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Modal de aprovação */}
      {showApprovedModal && (
        <div className="fixed inset-0 z-40 bg-black/70 backdrop-blur-sm flex items-center justify-center">
          <div className="bg-gray-900 border border-emerald-500/30 rounded-xl p-8 max-w-sm w-full mx-4 text-center">
            <div className="w-12 h-12 rounded-full bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center mx-auto mb-4 text-emerald-400">
              <CheckIcon />
            </div>
            <h3 className="font-mono font-semibold text-emerald-400 mb-1">Pesquisa aprovada!</h3>
            <p className="text-sm text-gray-500 font-mono mb-6">
              Keywords aprovadas. Pipeline avança automaticamente.
              {projetoResult && <span className="block mt-1 text-emerald-400/80">Projeto #{projetoResult.id} vinculado.</span>}
            </p>
            <button
              onClick={() => { setShowApprovedModal(false); onBack() }}
              className="w-full px-4 py-2.5 text-sm font-mono bg-emerald-600 text-white rounded-lg hover:bg-emerald-500 transition-all"
            >
              Voltar para lista de pesquisas
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── KwPlannerGate2 ───────────────────────────────────────────────
export function KwPlannerGate2() {
  const [view, setView] = useState<View>({ type: 'list' })

  if (view.type === 'scorecard') {
    return (
      <Gate2Scorecard
        pesquisaId={view.pesquisaId}
        onBack={() => setView({ type: 'list' })}
      />
    )
  }

  return <Gate2PesquisaList onSelect={id => setView({ type: 'scorecard', pesquisaId: id })} />
}
