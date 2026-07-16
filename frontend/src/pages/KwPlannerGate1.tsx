import { useState, useEffect, useCallback, useMemo } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { pesquisasApi, type Keyword } from '../lib/api'

// ─── Status config ────────────────────────────────────────────────
const STATUS_CFG = {
  pending_review:  { label: 'Aguardando revisão', cls: 'bg-amber-500/10 text-amber-400 border border-amber-500/25' },
  approved:        { label: 'Aprovada',           cls: 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/25' },
  rejected:        { label: 'Rejeitada',          cls: 'bg-red-500/10 text-red-400 border border-red-500/25' },
  classificado: { label: 'Classificado',  cls: 'bg-blue-500/10 text-blue-400 border border-blue-500/25' },
  aprovado:     { label: 'Aprovado',      cls: 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/25' },
} as const

type SortField = 'keyword' | 'avg_monthly_searches' | 'bid_pos1_4_brl' | 'score' | 'go_nogo' | 'kw_type' | 'board_note'

const KW_TYPE_CYCLE: Array<'principal' | 'silo' | 'geo' | 'descarta' | null> =
  ['principal', 'silo', 'geo', 'descarta', null]

const KW_TYPE_CFG = {
  principal: { label: 'principal', cls: 'bg-blue-500/10 text-blue-400 border-blue-500/30 hover:bg-blue-500/20' },
  silo:      { label: 'silo',      cls: 'bg-violet-500/10 text-violet-400 border-violet-500/30 hover:bg-violet-500/20' },
  geo:       { label: 'geo',       cls: 'bg-cyan-500/10 text-cyan-400 border-cyan-500/30 hover:bg-cyan-500/20' },
  descarta:  { label: 'descarta',  cls: 'bg-red-500/10 text-red-400 border-red-500/30 hover:bg-red-500/20' },
} as const

// ─── Icons ────────────────────────────────────────────────────────
function TrashIcon() {
  return (
    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
    </svg>
  )
}

function CheckIcon() {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
    </svg>
  )
}

function ChevronIcon({ expanded }: { expanded: boolean }) {
  return (
    <svg
      className={`w-3 h-3 transition-transform duration-150 ${expanded ? 'rotate-90' : ''}`}
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2.5}
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
    </svg>
  )
}

function Spinner({ size = 'sm' }: { size?: 'sm' | 'md' }) {
  const cls = size === 'sm' ? 'w-3.5 h-3.5' : 'w-5 h-5'
  return (
    <span className={`inline-block ${cls} border border-current border-t-transparent rounded-full animate-spin opacity-60`} />
  )
}

function SortIndicator({ field, sortField, sortDir }: { field: SortField; sortField: SortField | null; sortDir: 'asc' | 'desc' }) {
  if (sortField !== field) return <span className="ml-1 opacity-20">↕</span>
  return <span className="ml-1 text-emerald-400">{sortDir === 'desc' ? '▼' : '▲'}</span>
}

// ─── PesquisaList ─────────────────────────────────────────────────
function PesquisaList({ onSelect }: { onSelect: (id: string) => void }) {
  const queryClient = useQueryClient()
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; nome: string } | null>(null)
  const [deleting, setDeleting] = useState(false)

  const { data, isLoading, error } = useQuery({
    queryKey: ['pesquisas'],
    queryFn: pesquisasApi.list,
  })

  const handleDeletePesquisa = useCallback(async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await pesquisasApi.deletePesquisa(deleteTarget.id)
      queryClient.invalidateQueries({ queryKey: ['pesquisas'] })
    } finally {
      setDeleting(false)
      setDeleteTarget(null)
    }
  }, [deleteTarget, queryClient])

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      <header className="border-b border-gray-800 px-6 py-5">
        <div className="max-w-3xl mx-auto flex items-center gap-3">
          <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse shrink-0" />
          <div>
            <h1 className="font-mono font-bold tracking-tight text-gray-100">KW Planner — Gate 1</h1>
            <p className="text-xs text-gray-600 mt-0.5">Revisão de keywords antes de promover para BQ bronze</p>
          </div>
        </div>
      </header>

      {deleteTarget && (
        <div
          className="fixed inset-0 z-40 bg-black/70 backdrop-blur-sm flex items-center justify-center"
          onClick={() => !deleting && setDeleteTarget(null)}
        >
          <div
            className="bg-gray-900 border border-gray-800 rounded-xl p-6 max-w-sm w-full mx-4"
            onClick={e => e.stopPropagation()}
          >
            <h3 className="font-mono font-semibold text-gray-100 mb-1">Excluir pesquisa?</h3>
            <p className="text-sm text-gray-500 mb-1 font-mono">{deleteTarget.nome}</p>
            <p className="text-xs text-gray-700 mb-6 font-mono">
              A pesquisa e todas as suas keywords serão removidas permanentemente.
            </p>
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setDeleteTarget(null)}
                disabled={deleting}
                className="px-4 py-2 text-sm font-mono text-gray-500 hover:text-gray-200 transition-colors disabled:opacity-40"
              >
                Cancelar
              </button>
              <button
                onClick={handleDeletePesquisa}
                disabled={deleting}
                className="flex items-center gap-2 px-4 py-2 text-sm font-mono bg-red-600 text-white rounded-lg hover:bg-red-500 disabled:opacity-40 transition-all"
              >
                {deleting ? <><Spinner /> Excluindo...</> : 'Sim, excluir'}
              </button>
            </div>
          </div>
        </div>
      )}

      <main className="max-w-3xl mx-auto px-6 py-8">
        {isLoading && (
          <div className="flex items-center gap-2 text-gray-600 text-sm font-mono">
            <Spinner /> Carregando pesquisas...
          </div>
        )}
        {error && <p className="text-red-400 text-sm font-mono">Erro ao carregar pesquisas.</p>}
        {data?.length === 0 && (
          <p className="text-gray-700 text-sm font-mono">Nenhuma pesquisa no staging ainda.</p>
        )}
        <div className="grid gap-2">
          {data?.map(p => {
            const s = STATUS_CFG[p.status as keyof typeof STATUS_CFG] ?? STATUS_CFG.pending_review
            return (
              <button
                key={p.id}
                onClick={() => onSelect(p.id)}
                className="w-full text-left bg-gray-900 border border-gray-800 rounded-lg px-5 py-4 hover:border-gray-700 hover:bg-gray-800/60 transition-all duration-150 group"
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <span className="font-mono font-semibold text-gray-100 group-hover:text-white">
                      {p.projeto_nome}
                    </span>
                    <span className="text-gray-600 text-sm ml-2">{p.nicho} · {p.cidade}</span>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className={`text-xs font-mono px-2 py-0.5 rounded-full whitespace-nowrap ${s.cls}`}>
                      {s.label}
                    </span>
                    {p.status === 'rejected' && (
                      <button
                        onClick={e => { e.stopPropagation(); setDeleteTarget({ id: p.id, nome: p.projeto_nome }) }}
                        className="text-gray-700 hover:text-red-500 transition-colors p-0.5"
                        title="Excluir pesquisa rejeitada"
                      >
                        <TrashIcon />
                      </button>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-3 mt-2 text-xs font-mono text-gray-700">
                  {p.total_keywords != null && <span>{p.total_keywords} keywords</span>}
                  <span>{new Date(p.created_at).toLocaleDateString('pt-BR')}</span>
                </div>
              </button>
            )
          })}
        </div>
      </main>
    </div>
  )
}

// ─── KeywordRow ───────────────────────────────────────────────────
interface RowProps {
  kw: Keyword
  pesquisaId: string
  selected: boolean
  onSelect: (id: number, checked: boolean) => void
  onUpdate: (id: number, patch: Partial<Keyword>) => void
  onDelete: (id: number) => void
}

function KeywordRow({ kw, selected, onSelect, onUpdate, onDelete }: RowProps) {
  const [kwText, setKwText] = useState(kw.keyword)
  const [noteText, setNoteText] = useState(kw.board_note ?? '')
  const [expanded, setExpanded] = useState(false)
  const [editingNote, setEditingNote] = useState(false)
  const isGo = kw.go_nogo === 'GO'

  useEffect(() => { setKwText(kw.keyword) }, [kw.keyword])
  useEffect(() => { setNoteText(kw.board_note ?? '') }, [kw.board_note])

  const scoreColor =
    (kw.score ?? 0) >= 70 ? 'text-emerald-400' :
    (kw.score ?? 0) >= 40 ? 'text-amber-400' : 'text-red-400'

  const noteAccentCls = kw.kw_type
    ? ({
        principal: 'border-blue-500/40',
        silo:      'border-violet-500/40',
        geo:       'border-cyan-500/40',
        descarta:  'border-red-500/40',
      } as Record<string, string>)[kw.kw_type] ?? 'border-gray-700'
    : 'border-gray-700'

  return (
    <>
      <tr className={`border-b border-gray-800/40 ${selected ? 'bg-emerald-950/20' : 'hover:bg-gray-800/20'}`}>
        {/* Expand chevron */}
        <td className="pl-3 pr-1 py-2 w-6">
          <button
            onClick={() => setExpanded(p => !p)}
            className={`text-gray-600 hover:text-gray-300 transition-colors ${
              kw.board_note ? 'opacity-100' : 'opacity-30'
            }`}
            title={kw.board_note ? 'Ver justificativa' : 'Sem justificativa'}
          >
            <ChevronIcon expanded={expanded} />
          </button>
        </td>

        {/* Checkbox */}
        <td className="pl-2 pr-2 py-2 w-8">
          <input
            type="checkbox"
            checked={selected}
            onChange={e => onSelect(kw.id, e.target.checked)}
            className="w-3.5 h-3.5 accent-emerald-500 cursor-pointer"
          />
        </td>

        {/* Keyword */}
        <td className="px-3 py-2">
          <input
            value={kwText}
            onChange={e => setKwText(e.target.value)}
            onBlur={() => { if (kwText.trim() && kwText !== kw.keyword) onUpdate(kw.id, { keyword: kwText.trim() }) }}
            className="w-full min-w-[180px] bg-transparent font-mono text-sm text-gray-200 focus:outline-none border-b border-transparent focus:border-gray-600 transition-colors placeholder-gray-700"
          />
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

        {/* Score */}
        <td className="px-3 py-2 text-right w-16">
          <span className={`font-mono text-xs font-semibold ${scoreColor}`}>
            {kw.score != null ? Math.round(kw.score) : '—'}
          </span>
        </td>

        {/* GO / NO-GO toggle */}
        <td className="px-3 py-2 w-20 text-center">
          <button
            onClick={() => onUpdate(kw.id, { go_nogo: isGo ? 'NO-GO' : 'GO' })}
            className={`text-xs font-mono font-bold px-2.5 py-0.5 rounded border transition-all duration-150 ${
              isGo
                ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30 hover:bg-emerald-500/20'
                : 'bg-red-500/10 text-red-400 border-red-500/30 hover:bg-red-500/20'
            }`}
          >
            {kw.go_nogo ?? '—'}
          </button>
        </td>

        {/* kw_type toggle */}
        <td className="px-3 py-2 w-28 text-center">
          <button
            onClick={() => {
              const gate1Type = kw.kw_type as 'principal' | 'silo' | 'geo' | 'descarta' | null
              const idx = KW_TYPE_CYCLE.indexOf(gate1Type)
              const next = KW_TYPE_CYCLE[(idx + 1) % KW_TYPE_CYCLE.length]
              onUpdate(kw.id, { kw_type: next })
            }}
            className={`text-xs font-mono px-2.5 py-0.5 rounded border transition-all duration-150 ${
              kw.kw_type && kw.kw_type in KW_TYPE_CFG
                ? KW_TYPE_CFG[kw.kw_type as keyof typeof KW_TYPE_CFG].cls
                : 'text-gray-700 border-gray-800 hover:text-gray-500 hover:border-gray-700'
            }`}
          >
            {kw.kw_type && kw.kw_type in KW_TYPE_CFG ? KW_TYPE_CFG[kw.kw_type as keyof typeof KW_TYPE_CFG].label : (kw.kw_type ?? '—')}
          </button>
        </td>

        {/* Delete */}
        <td className="pl-2 pr-4 py-2 w-8 text-center">
          <button
            onClick={() => onDelete(kw.id)}
            className="text-gray-700 hover:text-red-500 transition-colors"
          >
            <TrashIcon />
          </button>
        </td>
      </tr>

      {/* Linha de justificativa expandida */}
      {expanded && (
        <tr className="border-b border-gray-800/40 bg-gray-900/40">
          <td colSpan={9} className="px-4 py-0">
            <div className={`border-l-2 ${noteAccentCls} ml-6 pl-3 py-2.5`}>
              {editingNote ? (
                <textarea
                  autoFocus
                  value={noteText}
                  onChange={e => setNoteText(e.target.value)}
                  onBlur={() => {
                    setEditingNote(false)
                    if (noteText !== (kw.board_note ?? '')) {
                      onUpdate(kw.id, { board_note: noteText || null as any })
                    }
                  }}
                  rows={2}
                  className="w-full bg-transparent font-mono text-xs text-gray-300 focus:outline-none resize-none placeholder-gray-700"
                  placeholder="Justificativa do agente (editável)..."
                />
              ) : (
                <p
                  onClick={() => setEditingNote(true)}
                  className="font-mono text-xs text-gray-400 cursor-text hover:text-gray-200 transition-colors min-h-[1.5rem]"
                  title="Clique para editar"
                >
                  {noteText || <span className="text-gray-700 italic">Sem justificativa — clique para adicionar</span>}
                </p>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

// ─── PesquisaReview ───────────────────────────────────────────────
function PesquisaReview({ pesquisaId, onBack }: { pesquisaId: string; onBack: () => void }) {
  const queryClient = useQueryClient()

  const [keywords, setKeywords] = useState<Keyword[]>([])
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [sortField, setSortField] = useState<SortField | null>(null)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [approving, setApproving] = useState(false)
  const [showApprovedModal, setShowApprovedModal] = useState(false)
  const [rejecting, setRejecting] = useState(false)
  const [showRejectConfirm, setShowRejectConfirm] = useState(false)
  const [showBulkDeleteConfirm, setShowBulkDeleteConfirm] = useState(false)
  const [showTypeWarning, setShowTypeWarning] = useState(false)

  const { data, isLoading, error } = useQuery({
    queryKey: ['pesquisa', pesquisaId],
    queryFn: () => pesquisasApi.get(pesquisaId),
  })

  useEffect(() => {
    if (data) setKeywords(data.keywords)
  }, [data])

  const goCount   = keywords.filter(k => k.go_nogo === 'GO').length
  const noGoCount = keywords.filter(k => k.go_nogo === 'NO-GO').length

  const handleSort = useCallback((field: SortField) => {
    setSortField(prev => {
      if (prev === field) {
        setSortDir(d => d === 'desc' ? 'asc' : 'desc')
        return field
      }
      setSortDir('desc')
      return field
    })
  }, [])

  const sortedKeywords = useMemo(() => {
    if (!sortField) return keywords
    return [...keywords].sort((a, b) => {
      const av = a[sortField]
      const bv = b[sortField]
      if (av == null && bv == null) return 0
      if (av == null) return 1
      if (bv == null) return -1
      let cmp: number
      if (typeof av === 'string' && typeof bv === 'string') {
        cmp = av.localeCompare(bv, 'pt-BR')
      } else {
        cmp = (av as number) - (bv as number)
      }
      return sortDir === 'desc' ? -cmp : cmp
    })
  }, [keywords, sortField, sortDir])

  // ── handlers ──
  const handleSelect = useCallback((id: number, checked: boolean) => {
    setSelected(prev => {
      const next = new Set(prev)
      checked ? next.add(id) : next.delete(id)
      return next
    })
  }, [])

  const handleSelectAllGo = useCallback(() => {
    setSelected(new Set(keywords.filter(k => k.go_nogo === 'GO').map(k => k.id)))
  }, [keywords])

  const handleSelectAllNoGo = useCallback(() => {
    setSelected(new Set(keywords.filter(k => k.go_nogo === 'NO-GO').map(k => k.id)))
  }, [keywords])

  const handleUpdate = useCallback(async (id: number, patch: Partial<Keyword>) => {
    setKeywords(prev => prev.map(k => k.id === id ? { ...k, ...patch } : k))
    try {
      await pesquisasApi.updateKeyword(pesquisaId, id, patch)
    } catch {
      const original = data?.keywords.find(k => k.id === id)
      if (original) setKeywords(prev => prev.map(k => k.id === id ? { ...k, ...original } : k))
    }
  }, [pesquisaId, data])

  const handleDelete = useCallback(async (id: number) => {
    setSelected(prev => { const next = new Set(prev); next.delete(id); return next })
    setKeywords(prev => prev.filter(k => k.id !== id))
    try {
      await pesquisasApi.deleteKeyword(pesquisaId, id)
    } catch {
      const original = data?.keywords.find(k => k.id === id)
      if (original) setKeywords(prev => [...prev, original].sort((a, b) => (b.score ?? 0) - (a.score ?? 0)))
    }
  }, [pesquisaId, data])

  const executeBulkDelete = useCallback(async () => {
    const ids = Array.from(selected)
    setShowBulkDeleteConfirm(false)
    setSelected(new Set())
    setKeywords(prev => prev.filter(k => !ids.includes(k.id)))
    const originals = ids.map(id => data?.keywords.find(k => k.id === id)).filter(Boolean) as typeof keywords
    await Promise.allSettled(
      ids.map(id =>
        pesquisasApi.deleteKeyword(pesquisaId, id).catch(() => {
          const original = originals.find(k => k.id === id)
          if (original) setKeywords(prev => [...prev, original].sort((a, b) => (b.score ?? 0) - (a.score ?? 0)))
        })
      )
    )
  }, [selected, pesquisaId, data])

  const handleApprove = async () => {
    if (selected.size === 0) return
    const selectedKws = keywords.filter(k => selected.has(k.id))
    const semTipo = selectedKws.filter(k => !k.kw_type).length
    if (semTipo > 0) {
      setShowTypeWarning(true)
      return
    }
    await doApprove()
  }

  const doApprove = async () => {
    setShowTypeWarning(false)
    setApproving(true)
    const texts = keywords.filter(k => selected.has(k.id)).map(k => k.keyword)
    try {
      await pesquisasApi.approve(pesquisaId, texts)
      queryClient.invalidateQueries({ queryKey: ['pesquisas'] })
      setApproving(false)
      setShowApprovedModal(true)
    } catch {
      setApproving(false)
    }
  }

  const handleReject = async () => {
    setRejecting(true)
    try {
      await pesquisasApi.reject(pesquisaId)
      queryClient.invalidateQueries({ queryKey: ['pesquisas'] })
      onBack()
    } catch {
      setRejecting(false)
      setShowRejectConfirm(false)
    }
  }

  // ── states ──
  if (isLoading) return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center">
      <div className="flex items-center gap-2.5 text-gray-600 text-sm font-mono">
        <Spinner size="md" /> Carregando...
      </div>
    </div>
  )

  if (error || !data) return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center">
      <p className="text-red-400 text-sm font-mono">Erro ao carregar pesquisa.</p>
    </div>
  )

  const { pesquisa } = data

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 pb-24">

      {/* Header */}
      <header className="sticky top-0 z-10 bg-gray-950/95 backdrop-blur border-b border-gray-800 px-6 py-3.5">
        <div className="max-w-6xl mx-auto flex items-center gap-4">
          <button
            onClick={onBack}
            className="font-mono text-sm text-gray-600 hover:text-gray-300 transition-colors"
          >
            ← voltar
          </button>
          <div className="h-4 w-px bg-gray-800" />
          <div className="min-w-0">
            <span className="font-mono font-bold text-gray-100">{pesquisa.projeto_nome}</span>
            <span className="text-gray-600 text-xs ml-2">{pesquisa.nicho} · {pesquisa.cidade}</span>
            <button
              onClick={() => navigator.clipboard.writeText(pesquisaId)}
              className="ml-3 font-mono text-xs text-gray-700 hover:text-gray-400 transition-colors cursor-pointer"
              title="Clique para copiar pesquisa_id"
            >
              {pesquisaId}
            </button>
          </div>
          <div className="ml-auto flex items-center gap-4 text-xs font-mono shrink-0">
            <span className="text-gray-600">{keywords.length} kw</span>
            <span className="text-emerald-400">{goCount} GO</span>
            <span className="text-red-400">{noGoCount} NO-GO</span>
          </div>
        </div>
      </header>

      {/* Toolbar */}
      <div className="max-w-6xl mx-auto px-6 py-2.5 flex items-center gap-2 border-b border-gray-800/40">
        <button
          onClick={handleSelectAllGo}
          className="px-2.5 py-1 text-xs font-mono rounded border border-emerald-500/25 text-emerald-400/70 bg-emerald-500/5 hover:bg-emerald-500/15 hover:text-emerald-400 hover:border-emerald-500/40 transition-all"
        >
          selecionar todos GO
        </button>
        <button
          onClick={handleSelectAllNoGo}
          className="px-2.5 py-1 text-xs font-mono rounded border border-red-500/25 text-red-400/70 bg-red-500/5 hover:bg-red-500/15 hover:text-red-400 hover:border-red-500/40 transition-all"
        >
          selecionar todos NO-GO
        </button>
        <button
          onClick={() => { setSelected(new Set(keywords.map(k => k.id))) }}
          className="px-2.5 py-1 text-xs font-mono rounded border border-gray-700 text-gray-500 bg-gray-900 hover:bg-gray-800 hover:text-gray-300 hover:border-gray-600 transition-all"
        >
          selecionar todos
        </button>
        <button
          onClick={() => setSelected(new Set())}
          className="px-2.5 py-1 text-xs font-mono rounded border border-gray-800 text-gray-600 bg-transparent hover:bg-gray-900 hover:text-gray-400 hover:border-gray-700 transition-all"
        >
          limpar seleção
        </button>
      </div>

      {/* Table */}
      <div className="max-w-6xl mx-auto px-6 py-4">
        <div className="rounded-lg border border-gray-800 overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-gray-800 bg-gray-900/80">
                <th className="pl-3 pr-1 py-3 w-6" />
                <th className="pl-2 pr-2 py-3 w-8" />
                <th className="px-3 py-3 text-left w-auto">
                  <button onClick={() => handleSort('keyword')} className="flex items-center text-xs font-mono font-medium uppercase tracking-wider text-gray-600 hover:text-gray-300 transition-colors">
                    Keyword<SortIndicator field="keyword" sortField={sortField} sortDir={sortDir} />
                  </button>
                </th>
                <th className="px-3 py-3 text-right w-24">
                  <button onClick={() => handleSort('avg_monthly_searches')} className="flex items-center justify-end w-full text-xs font-mono font-medium uppercase tracking-wider text-gray-600 hover:text-gray-300 transition-colors">
                    Vol/mês<SortIndicator field="avg_monthly_searches" sortField={sortField} sortDir={sortDir} />
                  </button>
                </th>
                <th className="px-3 py-3 text-right w-24">
                  <button onClick={() => handleSort('bid_pos1_4_brl')} className="flex items-center justify-end w-full text-xs font-mono font-medium uppercase tracking-wider text-gray-600 hover:text-gray-300 transition-colors">
                    CPC<SortIndicator field="bid_pos1_4_brl" sortField={sortField} sortDir={sortDir} />
                  </button>
                </th>
                <th className="px-3 py-3 text-right w-16">
                  <button onClick={() => handleSort('score')} className="flex items-center justify-end w-full text-xs font-mono font-medium uppercase tracking-wider text-gray-600 hover:text-gray-300 transition-colors">
                    Score<SortIndicator field="score" sortField={sortField} sortDir={sortDir} />
                  </button>
                </th>
                <th className="px-3 py-3 text-center w-20">
                  <button onClick={() => handleSort('go_nogo')} className="flex items-center justify-center w-full text-xs font-mono font-medium uppercase tracking-wider text-gray-600 hover:text-gray-300 transition-colors">
                    Status<SortIndicator field="go_nogo" sortField={sortField} sortDir={sortDir} />
                  </button>
                </th>
                <th className="px-3 py-3 text-center w-28">
                  <button onClick={() => handleSort('kw_type')} className="flex items-center justify-center w-full text-xs font-mono font-medium uppercase tracking-wider text-gray-600 hover:text-gray-300 transition-colors">
                    Tipo<SortIndicator field="kw_type" sortField={sortField} sortDir={sortDir} />
                  </button>
                </th>
                <th className="pl-2 pr-4 py-3 w-8" />
              </tr>
            </thead>
            <tbody>
              {sortedKeywords.map(kw => (
                <KeywordRow
                  key={kw.id}
                  kw={kw}
                  pesquisaId={pesquisaId}
                  selected={selected.has(kw.id)}
                  onSelect={handleSelect}
                  onUpdate={handleUpdate}
                  onDelete={handleDelete}
                />
              ))}
              {keywords.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-4 py-8 text-center text-sm font-mono text-gray-700">
                    Nenhuma keyword no staging.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Sticky action bar */}
      <div className="fixed bottom-0 left-0 right-0 z-20 border-t border-gray-800 bg-gray-950/90 backdrop-blur px-6 py-3.5">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <span className="text-sm font-mono text-gray-600">
            {selected.size > 0
              ? <><span className="text-gray-200 font-semibold">{selected.size}</span> selecionadas</>
              : 'Nenhuma keyword selecionada'}
          </span>
          <div className="flex items-center gap-3">
            {selected.size > 0 && (
              <button
                onClick={() => setShowBulkDeleteConfirm(true)}
                className="flex items-center gap-1.5 px-4 py-2 text-sm font-mono rounded-lg border border-red-500/30 text-red-400/80 hover:border-red-500/60 hover:text-red-400 transition-all"
              >
                <TrashIcon />
                Apagar ({selected.size})
              </button>
            )}
            <button
              onClick={() => setShowRejectConfirm(true)}
              className="px-4 py-2 text-sm font-mono border border-gray-700 text-gray-500 rounded-lg hover:border-gray-600 hover:text-gray-400 transition-all"
            >
              Rejeitar Pesquisa
            </button>
            <button
              onClick={handleApprove}
              disabled={selected.size === 0 || approving}
              className="flex items-center gap-2 px-4 py-2 text-sm font-mono bg-emerald-600 text-white rounded-lg hover:bg-emerald-500 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
            >
              {approving ? <><Spinner /> Aprovando...</> : `Aprovar ${selected.size > 0 ? `(${selected.size})` : ''} →`}
            </button>
          </div>
        </div>
      </div>

      {/* Bulk delete confirm modal */}
      {/* Approve success modal */}
      {showApprovedModal && (
        <div className="fixed inset-0 z-40 bg-black/70 backdrop-blur-sm flex items-center justify-center">
          <div className="bg-gray-900 border border-emerald-500/30 rounded-xl p-8 max-w-sm w-full mx-4 text-center">
            <div className="w-12 h-12 rounded-full bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center mx-auto mb-4 text-emerald-400">
              <CheckIcon />
            </div>
            <h3 className="font-mono font-semibold text-emerald-400 mb-1">Keywords aprovadas!</h3>
            <p className="text-sm text-gray-500 font-mono mb-6">Promovendo para BQ bronze via Kestra...</p>
            <button
              onClick={() => { setShowApprovedModal(false); onBack() }}
              className="w-full px-4 py-2.5 text-sm font-mono bg-emerald-600 text-white rounded-lg hover:bg-emerald-500 transition-all"
            >
              Voltar para lista de pesquisas
            </button>
          </div>
        </div>
      )}

      {showBulkDeleteConfirm && (
        <div
          className="fixed inset-0 z-30 bg-black/70 backdrop-blur-sm flex items-center justify-center"
          onClick={() => setShowBulkDeleteConfirm(false)}
        >
          <div
            className="bg-gray-900 border border-gray-800 rounded-xl p-6 max-w-sm w-full mx-4"
            onClick={e => e.stopPropagation()}
          >
            <h3 className="font-mono font-semibold text-gray-100 mb-1">Apagar {selected.size} keyword{selected.size !== 1 ? 's' : ''}?</h3>
            <p className="text-sm text-gray-500 mb-6 font-mono">
              As keywords selecionadas serão removidas do staging. Não é possível desfazer.
            </p>
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setShowBulkDeleteConfirm(false)}
                className="px-4 py-2 text-sm font-mono text-gray-500 hover:text-gray-200 transition-colors"
              >
                Cancelar
              </button>
              <button
                onClick={executeBulkDelete}
                className="flex items-center gap-2 px-4 py-2 text-sm font-mono bg-red-600 text-white rounded-lg hover:bg-red-500 transition-all"
              >
                Sim, apagar
              </button>
            </div>
          </div>
        </div>
      )}

      {/* kw_type warning modal */}
      {showTypeWarning && (
        <div
          className="fixed inset-0 z-30 bg-black/70 backdrop-blur-sm flex items-center justify-center"
          onClick={() => setShowTypeWarning(false)}
        >
          <div
            className="bg-gray-900 border border-amber-500/30 rounded-xl p-6 max-w-sm w-full mx-4"
            onClick={e => e.stopPropagation()}
          >
            <h3 className="font-mono font-semibold text-amber-400 mb-1">Tipo não definido</h3>
            <p className="text-sm text-gray-400 mb-2 font-mono">
              {keywords.filter(k => selected.has(k.id) && !k.kw_type).length} keyword{keywords.filter(k => selected.has(k.id) && !k.kw_type).length !== 1 ? 's' : ''} selecionada{keywords.filter(k => selected.has(k.id) && !k.kw_type).length !== 1 ? 's' : ''} sem tipo classificado.
            </p>
            <p className="text-xs text-gray-600 mb-6 font-mono">
              Defina o tipo (principal / silo / geo / descarta) antes de aprovar, ou prossiga mesmo assim.
            </p>
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setShowTypeWarning(false)}
                className="px-4 py-2 text-sm font-mono text-gray-400 hover:text-gray-200 transition-colors"
              >
                Voltar e classificar
              </button>
              <button
                onClick={doApprove}
                className="flex items-center gap-2 px-4 py-2 text-sm font-mono bg-amber-600 text-white rounded-lg hover:bg-amber-500 transition-all"
              >
                Aprovar mesmo assim
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Reject confirm modal */}
      {showRejectConfirm && (
        <div
          className="fixed inset-0 z-30 bg-black/70 backdrop-blur-sm flex items-center justify-center"
          onClick={() => setShowRejectConfirm(false)}
        >
          <div
            className="bg-gray-900 border border-gray-800 rounded-xl p-6 max-w-sm w-full mx-4"
            onClick={e => e.stopPropagation()}
          >
            <h3 className="font-mono font-semibold text-gray-100 mb-1">Rejeitar pesquisa?</h3>
            <p className="text-sm text-gray-500 mb-6 font-mono">
              Todas as keywords serão removidas do staging. Não é possível desfazer.
            </p>
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setShowRejectConfirm(false)}
                className="px-4 py-2 text-sm font-mono text-gray-500 hover:text-gray-200 transition-colors"
              >
                Cancelar
              </button>
              <button
                onClick={handleReject}
                disabled={rejecting}
                className="flex items-center gap-2 px-4 py-2 text-sm font-mono bg-red-600 text-white rounded-lg hover:bg-red-500 disabled:opacity-40 transition-all"
              >
                {rejecting ? <><Spinner /> Rejeitando...</> : 'Sim, rejeitar'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── KwPlannerGate1 ───────────────────────────────────────────────
type View = { type: 'list' } | { type: 'review'; pesquisaId: string }

export function KwPlannerGate1() {
  const [view, setView] = useState<View>({ type: 'list' })

  if (view.type === 'review') {
    return (
      <PesquisaReview
        pesquisaId={view.pesquisaId}
        onBack={() => setView({ type: 'list' })}
      />
    )
  }

  return <PesquisaList onSelect={id => setView({ type: 'review', pesquisaId: id })} />
}
