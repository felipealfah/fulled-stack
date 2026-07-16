import { useState, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { projetosApi, prospeccaoApi, type LeadProspeccao, type LeadProspeccaoStatus, type LeadProspeccaoUpdate } from '../lib/api'

// ── Config do funil ───────────────────────────────────────────────────────────

const FUNIL: { status: LeadProspeccaoStatus; label: string; cls: string; col: string }[] = [
  { status: 'novo',                label: 'Novo',            cls: 'bg-blue-500/10 text-blue-400 border border-blue-500/25',       col: 'border-blue-500/30' },
  { status: 'redesenhado',         label: 'Redesenhado',     cls: 'bg-violet-500/10 text-violet-400 border border-violet-500/25', col: 'border-violet-500/30' },
  { status: 'publicado',           label: 'Publicado',       cls: 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/25',       col: 'border-cyan-500/30' },
  { status: 'proposta_enviada',    label: 'Proposta',        cls: 'bg-amber-500/10 text-amber-400 border border-amber-500/25',    col: 'border-amber-500/30' },
  { status: 'negociacao',          label: 'Negociação',      cls: 'bg-orange-500/10 text-orange-400 border border-orange-500/25', col: 'border-orange-500/30' },
  { status: 'fechado',             label: 'Fechado',         cls: 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/40', col: 'border-emerald-500/40' },
  { status: 'perdido',             label: 'Perdido',         cls: 'bg-red-500/10 text-red-400 border border-red-500/25',          col: 'border-red-500/30' },
  { status: 'inquilino_potencial', label: 'Inquilino Pot.',  cls: 'bg-teal-500/10 text-teal-400 border border-teal-500/25',       col: 'border-teal-500/30' },
]

const STATUS_CFG = Object.fromEntries(FUNIL.map(f => [f.status, f])) as Record<LeadProspeccaoStatus, typeof FUNIL[number]>

const brl = (v: number | null | undefined) =>
  (Number(v) || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', maximumFractionDigits: 0 })

function Spinner({ size = 'sm' }: { size?: 'sm' | 'md' }) {
  const cls = size === 'sm' ? 'w-3.5 h-3.5' : 'w-5 h-5'
  return (
    <span className={`inline-block ${cls} border border-current border-t-transparent rounded-full animate-spin opacity-60`} />
  )
}

// ── Card (compartilhado kanban/lista) ─────────────────────────────────────────

function LeadCard({ lead, updating, compact, onDragStart, onDelete }: {
  lead: LeadProspeccao
  updating: boolean
  compact?: boolean
  onDragStart?: (e: React.DragEvent, slug: string) => void
  onDelete?: (slug: string) => void
}) {
  return (
    <div
      draggable={!!onDragStart}
      onDragStart={e => onDragStart?.(e, lead.slug)}
      className={`group relative bg-gray-900 border border-gray-800 rounded-lg px-4 py-3 hover:border-gray-600 transition-all ${onDragStart ? 'cursor-grab active:cursor-grabbing' : ''} ${updating ? 'opacity-50' : ''}`}
    >
      {onDelete && (
        <button
          onClick={e => { e.stopPropagation(); onDelete(lead.slug) }}
          title="Excluir lead"
          className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity text-gray-600 hover:text-red-400 text-xs leading-none p-1 rounded hover:bg-red-500/10"
        >
          ✕
        </button>
      )}
      <div className="flex items-center gap-2">
        <span className="font-mono font-semibold text-sm text-gray-100 truncate">{lead.nome}</span>
        {updating && <Spinner />}
      </div>
      <div className="text-[11px] font-mono text-gray-600 mt-0.5 truncate">
        {[lead.nicho, lead.cidade].filter(Boolean).join(' · ')}
        {lead.nota != null && <span className="text-amber-400"> · {Number(lead.nota).toFixed(1)}★</span>}
      </div>
      {!compact && lead.motivo_site_ruim && (
        <p className="text-[11px] font-mono text-gray-500 mt-1.5 line-clamp-2">{lead.motivo_site_ruim}</p>
      )}
      {lead.resumo_resposta && (
        <p className="text-[11px] font-mono text-orange-300/80 mt-1.5 line-clamp-2">💬 {lead.resumo_resposta}</p>
      )}
      <div className="flex items-center gap-2 mt-1.5 text-[11px] font-mono flex-wrap">
        {lead.site_url && (
          <a href={lead.site_url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} className="text-gray-500 hover:text-gray-300 underline underline-offset-2">site</a>
        )}
        {lead.url_preview && (
          <a href={lead.url_preview} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} className="text-cyan-400 hover:text-cyan-300 underline underline-offset-2">preview</a>
        )}
        {lead.followup_em && lead.status === 'proposta_enviada' && (
          <span className="text-gray-600" title={`Follow-up em ${new Date(lead.followup_em).toLocaleDateString('pt-BR')}`}>follow-up ✓</span>
        )}
        {lead.contrato_status && (
          <span className={lead.contrato_status === 'assinado' ? 'text-emerald-400' : 'text-amber-400'}>
            contrato {lead.contrato_status}
          </span>
        )}
      </div>
      {(lead.valor_fechado != null || lead.manutencao_mensal != null) && (
        <div className="mt-1.5 text-[11px] font-mono text-emerald-400/90">
          {lead.valor_fechado != null && <span>{brl(lead.valor_fechado)}</span>}
          {lead.manutencao_mensal != null && <span className="text-teal-400"> + {brl(lead.manutencao_mensal)}/mês</span>}
          <span className={lead.pago ? 'text-emerald-400' : 'text-amber-400'}> · {lead.pago ? 'pago' : 'a receber'}</span>
        </div>
      )}
    </div>
  )
}

// ── Página ────────────────────────────────────────────────────────────────────

export function Prospeccao() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [visao, setVisao] = useState<'kanban' | 'lista'>('kanban')
  const [updatingSlug, setUpdatingSlug] = useState<string | null>(null)
  const [dragOverCol, setDragOverCol] = useState<LeadProspeccaoStatus | null>(null)

  const { data: projeto } = useQuery({
    queryKey: ['projeto', id],
    queryFn: () => projetosApi.get(id!),
    enabled: !!id,
  })

  const { data: leads, isLoading, error, dataUpdatedAt } = useQuery({
    queryKey: ['prospeccao-leads', id ?? 'todas'],
    queryFn: () => prospeccaoApi.listLeads(id ? { projeto_id: id } : undefined),
    refetchInterval: 5000, // agentes (Claude Code/Cowork) gravam via API — refletir sem F5
  })

  const ativos = useMemo(() => (leads ?? []).filter(l => l.status !== 'descartado'), [leads])
  const descartados = useMemo(() => (leads ?? []).filter(l => l.status === 'descartado'), [leads])

  const porStatus = useMemo(() => {
    const m = Object.fromEntries(FUNIL.map(f => [f.status, [] as LeadProspeccao[]]))
    for (const l of ativos) m[l.status]?.push(l)
    return m as Record<LeadProspeccaoStatus, LeadProspeccao[]>
  }, [ativos])

  const fin = useMemo(() => {
    const fechados = porStatus['fechado'] ?? []
    return {
      fechados: fechados.length,
      receita: fechados.reduce((s, l) => s + (Number(l.valor_fechado) || 0), 0),
      mrr: fechados.reduce((s, l) => s + (Number(l.manutencao_mensal) || 0), 0),
      aReceber: fechados.filter(l => !l.pago).reduce((s, l) => s + (Number(l.valor_fechado) || 0), 0),
    }
  }, [porStatus])

  async function patchLead(slug: string, data: LeadProspeccaoUpdate) {
    setUpdatingSlug(slug)
    try {
      await prospeccaoApi.updateLead(slug, data)
      queryClient.invalidateQueries({ queryKey: ['prospeccao-leads'] })
    } catch {
      // silent — estado atual permanece
    } finally {
      setUpdatingSlug(null)
    }
  }

  async function handleDelete(slug: string) {
    const lead = ativos.find(l => l.slug === slug)
    if (!window.confirm(`Excluir "${lead?.nome ?? slug}" permanentemente?\n\nO lead será removido do banco — poderá ser reprospecctado no futuro.\nPara apenas descartá-lo sem reprospectar, arraste para "Perdido".`)) return
    setUpdatingSlug(slug)
    try {
      await prospeccaoApi.deleteLead(slug)
      queryClient.invalidateQueries({ queryKey: ['prospeccao-leads'] })
    } catch {
      // silent
    } finally {
      setUpdatingSlug(null)
    }
  }

  function handleDrop(e: React.DragEvent, destino: LeadProspeccaoStatus) {
    e.preventDefault()
    setDragOverCol(null)
    const slug = e.dataTransfer.getData('text/plain')
    const lead = ativos.find(l => l.slug === slug)
    if (!slug || !lead || lead.status === destino) return

    const data: LeadProspeccaoUpdate = { status: destino }
    if (destino === 'fechado') {
      const valor = window.prompt(`Fechou! Valor do site (R$) para ${lead.nome}:`, lead.valor_fechado?.toString() ?? '')
      if (valor === null) return // cancelou o fechamento
      const manut = window.prompt('Manutenção mensal (R$) — vazio se não contratou:', lead.manutencao_mensal?.toString() ?? '')
      if (valor.trim()) data.valor_fechado = Number(valor.replace(',', '.'))
      if (manut?.trim()) data.manutencao_mensal = Number(manut.replace(',', '.'))
    }
    patchLead(slug, data)
  }

  if (isLoading) return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center">
      <div className="flex items-center gap-2.5 text-gray-600 text-sm font-mono">
        <Spinner size="md" /> Carregando leads...
      </div>
    </div>
  )

  if (error) return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center">
      <p className="text-red-400 text-sm font-mono">Erro ao carregar leads. Verifique a conexão com a API.</p>
    </div>
  )

  return (
    <div className="min-h-screen bg-gray-950 flex flex-col">
      {/* Header */}
      <header className="border-b border-gray-800 px-6 py-4">
        {id && (
          <button
            onClick={() => navigate(`/projetos/${id}`)}
            className="text-xs font-mono text-gray-600 hover:text-gray-300 mb-1"
          >
            ← {projeto?.projeto_nome ?? 'Projeto'}
          </button>
        )}
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div>
            <h1 className="font-mono font-semibold tracking-tight text-gray-100">
              {id ? 'Funil da Campanha' : 'Prospecção — todas as campanhas'}
            </h1>
            <p className="text-xs text-gray-600 font-mono mt-0.5">
              {ativos.length} leads · {descartados.length} descartados
              {dataUpdatedAt ? ` · sync ${new Date(dataUpdatedAt).toLocaleTimeString('pt-BR')}` : ''}
            </p>
          </div>

          {/* Financeiro */}
          <div className="flex items-center gap-4 text-xs font-mono flex-wrap">
            <span className="text-gray-500">Fechados <span className="text-emerald-400 font-semibold">{fin.fechados}</span></span>
            <span className="text-gray-500">One-off <span className="text-emerald-400 font-semibold">{brl(fin.receita)}</span></span>
            <span className="text-gray-500">MRR <span className="text-teal-400 font-semibold">{brl(fin.mrr)}/mês</span></span>
            <span className="text-gray-500">A receber <span className="text-amber-400 font-semibold">{brl(fin.aReceber)}</span></span>
          </div>

          {/* Toggle visão */}
          <div className="flex items-center gap-1 border border-gray-800 rounded-lg p-0.5">
            {(['kanban', 'lista'] as const).map(v => (
              <button
                key={v}
                onClick={() => setVisao(v)}
                className={`px-3 py-1 text-xs font-mono rounded-md ${
                  visao === v ? 'bg-amber-500/15 text-amber-400' : 'text-gray-500 hover:text-gray-300'
                }`}
              >
                {v === 'kanban' ? 'Kanban' : 'Lista'}
              </button>
            ))}
          </div>
        </div>
      </header>

      {/* Kanban */}
      {visao === 'kanban' ? (
        <div className="flex-1 overflow-x-auto px-4 py-4">
          <div className="flex gap-3 min-h-full items-start" style={{ minWidth: 'max-content' }}>
            {FUNIL.map(f => (
              <div
                key={f.status}
                onDragOver={e => { e.preventDefault(); setDragOverCol(f.status) }}
                onDragLeave={() => setDragOverCol(c => (c === f.status ? null : c))}
                onDrop={e => handleDrop(e, f.status)}
                className={`w-64 shrink-0 rounded-xl border bg-gray-900/40 transition-colors ${
                  dragOverCol === f.status ? `${f.col} bg-gray-900` : 'border-gray-800/70'
                }`}
              >
                <div className="px-3 py-2.5 flex items-center justify-between border-b border-gray-800/70">
                  <span className={`text-xs font-mono px-2 py-0.5 rounded-full ${f.cls}`}>{f.label}</span>
                  <span className="text-xs font-mono text-gray-600">{porStatus[f.status]?.length ?? 0}</span>
                </div>
                <div className="p-2 flex flex-col gap-2 min-h-[120px]">
                  {(porStatus[f.status] ?? []).map(lead => (
                    <LeadCard
                      key={lead.id}
                      lead={lead}
                      compact
                      updating={updatingSlug === lead.slug}
                      onDragStart={(e, slug) => e.dataTransfer.setData('text/plain', slug)}
                      onDelete={handleDelete}
                    />
                  ))}
                  {(porStatus[f.status] ?? []).length === 0 && (
                    <div className="text-[11px] font-mono text-gray-700 text-center py-6 select-none">solte aqui</div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        /* Lista */
        <div className="max-w-3xl w-full mx-auto px-6 py-5">
          {ativos.length === 0 ? (
            <div className="flex flex-col items-center gap-3 py-16 text-center">
              <h2 className="font-mono font-semibold text-gray-400">Nenhum lead aqui</h2>
              <p className="font-mono text-sm text-gray-600 max-w-sm">
                Rode <span className="text-amber-400">/prospectar</span> no plugin prospector para alimentar este funil.
              </p>
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              {ativos.map(lead => (
                <div key={lead.id} className="relative">
                  <LeadCard lead={lead} updating={updatingSlug === lead.slug} onDelete={handleDelete} />
                  <select
                    value={lead.status}
                    disabled={updatingSlug === lead.slug}
                    onChange={e => patchLead(lead.slug, { status: e.target.value as LeadProspeccaoStatus })}
                    className={`absolute top-3 right-3 text-xs font-mono px-2 py-1 rounded-lg cursor-pointer focus:outline-none disabled:opacity-40 bg-gray-950 ${STATUS_CFG[lead.status]?.cls ?? 'text-gray-400 border border-gray-700'}`}
                  >
                    {FUNIL.map(f => (
                      <option key={f.status} value={f.status} className="bg-gray-900 text-gray-200">{f.label}</option>
                    ))}
                  </select>
                </div>
              ))}
              {descartados.length > 0 && (
                <p className="text-xs font-mono text-gray-700 mt-3">+ {descartados.length} descartados (não exibidos)</p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
