import { useState, useEffect, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'
import {
  LineChart, Line, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import { rankingApi, type RankingRow, type RankingKeywordHistory } from '../lib/api'

const STATUS_CFG = {
  RANKEANDO: { label: 'Rankeando', cls: 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30' },
  GAP:       { label: 'Gap',       cls: 'bg-red-500/10 text-red-400 border border-red-500/30' },
  SURPRESA:  { label: 'Surpresa',  cls: 'bg-amber-500/10 text-amber-400 border border-amber-500/25' },
  BLOQUEADO: { label: 'Bloqueado', cls: 'bg-gray-500/10 text-gray-500 border border-gray-700' },
  PROMOVIDO: { label: 'Promovido', cls: 'bg-violet-500/10 text-violet-400 border border-violet-500/30' },
} as const

const KW_TYPES = ['PAGINA_PRINCIPAL', 'PAGINA_GEO', 'SECAO', 'DESCARTA'] as const

function StatusChip({ status }: { status: keyof typeof STATUS_CFG }) {
  const cfg = STATUS_CFG[status] ?? STATUS_CFG.GAP
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider ${cfg.cls}`}>
      {cfg.label}
    </span>
  )
}

type SortField = 'keyword' | 'kw_type' | 'sc_position' | 'srp_position' | 'status' | 'sc_impressions_30d' | 'sc_clicks_30d' | 'receita_potencial' | 'avg_monthly_searches'
type SortDir = 'asc' | 'desc'
const STATUS_ORDER = { RANKEANDO: 0, PROMOVIDO: 1, SURPRESA: 2, GAP: 3, BLOQUEADO: 4 }

const CHART_COLORS = [
  '#34d399', '#60a5fa', '#f472b6', '#fb923c', '#a78bfa',
  '#facc15', '#22d3ee', '#4ade80', '#f87171', '#818cf8',
]

function sortValue(row: RankingRow, field: SortField): number | string {
  switch (field) {
    case 'keyword':           return row.keyword ?? ''
    case 'kw_type':           return row.kw_type ?? ''
    case 'sc_position':       return row.sc_position_avg_30d ?? 9999
    case 'srp_position':      return row.serp_position ?? 9999
    case 'status':            return STATUS_ORDER[row.status] ?? 9
    case 'sc_impressions_30d':   return row.sc_impressions_30d ?? -1
    case 'sc_clicks_30d':        return row.sc_clicks_30d ?? -1
    case 'receita_potencial':    return row.receita_potencial ?? -1
    case 'avg_monthly_searches': return row.avg_monthly_searches ?? -1
  }
}

function SortHeader({ label, field, sort, onSort, align = 'right' }: {
  label: string; field: SortField
  sort: { field: SortField; dir: SortDir }; onSort: (f: SortField) => void; align?: 'left' | 'right'
}) {
  const active = sort.field === field
  return (
    <th
      onClick={() => onSort(field)}
      className={`px-4 py-3 text-[10px] uppercase tracking-wider cursor-pointer select-none
                  hover:text-gray-400 transition-colors ${active ? 'text-gray-400' : 'text-gray-600'}
                  ${align === 'right' ? 'text-right' : 'text-left'}`}
    >
      {label}{active ? (sort.dir === 'asc' ? ' ↑' : ' ↓') : ''}
    </th>
  )
}

// ── Modal de promoção ────────────────────────────────────────────────────────
function PromoteModal({ keyword, onConfirm, onClose }: {
  keyword: string; onConfirm: (kw_type: string) => void; onClose: () => void
}) {
  const [kwType, setKwType] = useState<string>('PAGINA_GEO')
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 w-80 shadow-xl font-mono">
        <h2 className="text-sm text-gray-100 mb-1">Promover keyword</h2>
        <p className="text-xs text-gray-500 mb-4 break-all">{keyword}</p>
        <label className="text-[10px] text-gray-600 uppercase tracking-wider">Tipo de página</label>
        <select
          value={kwType}
          onChange={e => setKwType(e.target.value)}
          className="w-full mt-1 mb-5 bg-gray-800 border border-gray-700 text-gray-100 text-xs rounded px-2 py-1.5"
        >
          {KW_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="px-3 py-1.5 text-xs text-gray-500 hover:text-gray-300">Cancelar</button>
          <button
            onClick={() => onConfirm(kwType)}
            className="px-3 py-1.5 text-xs bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 rounded hover:bg-emerald-500/20"
          >
            Promover
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Botões de ação por linha ─────────────────────────────────────────────────
function RowActions({ row, isOverridden, onAction }: {
  row: RankingRow; isOverridden: boolean
  onAction: (keyword: string, action: 'promote' | 'block' | 'remove') => void
}) {
  if (isOverridden) {
    return (
      <button
        onClick={() => onAction(row.keyword, 'remove')}
        className="text-[10px] text-gray-600 hover:text-red-400 transition-colors px-1"
        title="Remover override"
      >
        ✕
      </button>
    )
  }
  return (
    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
      {row.status === 'SURPRESA' && (
        <button
          onClick={() => onAction(row.keyword, 'promote')}
          className="text-[10px] text-emerald-600 hover:text-emerald-400 transition-colors px-1"
          title="Promover para plano"
        >
          +
        </button>
      )}
      <button
        onClick={() => onAction(row.keyword, 'block')}
        className="text-[10px] text-gray-600 hover:text-red-400 transition-colors px-1"
        title="Bloquear (não consumir quota SERP)"
      >
        🚫
      </button>
    </div>
  )
}

// ── Histórico de ranking ─────────────────────────────────────────────────────
function HistoryChart({ projetoId, rankeandoKeywords }: {
  projetoId: string
  rankeandoKeywords: string[]
}) {
  const [selected, setSelected] = useState<string[]>(rankeandoKeywords.slice(0, 5))

  const { data, isLoading } = useQuery({
    queryKey: ['ranking-history', projetoId],
    queryFn: () => rankingApi.history(projetoId),
    staleTime: 5 * 60 * 1000,
  })

  function toggleKeyword(kw: string) {
    setSelected(prev =>
      prev.includes(kw)
        ? prev.filter(k => k !== kw)
        : prev.length < 10 ? [...prev, kw] : prev
    )
  }

  if (isLoading) return (
    <p className="font-mono text-sm text-gray-600 text-center py-16">Carregando histórico...</p>
  )

  if (!data || data.status === 'not_ready') return (
    <div className="text-center py-16">
      <p className="font-mono text-sm text-gray-600">Sem dados de histórico.</p>
      <p className="font-mono text-xs text-gray-700 mt-1">Execute o pipeline rank_intel para começar a acumular dados.</p>
    </div>
  )

  const allKws = data.keywords ?? []
  const kwMap = new Map<string, RankingKeywordHistory>(allKws.map(k => [k.keyword, k]))

  const allDates = Array.from(
    new Set(allKws.flatMap(k => k.series.map(s => s.date)))
  ).sort()

  const singleSnapshot = allDates.length < 2

  const chartData = allDates.map(d => {
    const point: Record<string, string | number | null> = { date: d }
    for (const kw of selected) {
      const hist = kwMap.get(kw)
      const entry = hist?.series.find(s => s.date === d)
      point[kw] = entry?.serp_position ?? entry?.sc_position ?? null
    }
    return point
  })

  if (singleSnapshot) return (
    <div className="text-center py-16 space-y-2">
      <p className="font-mono text-sm text-gray-400">
        Apenas 1 snapshot disponível ({allDates[0] ?? '—'}).
      </p>
      <p className="font-mono text-xs text-gray-600">
        O gráfico de histórico aparecerá após a segunda execução do rank_intel.
      </p>
    </div>
  )

  return (
    <div className="space-y-4">
      {/* Seletor de keywords */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <p className="font-mono text-[10px] text-gray-600 uppercase tracking-wider mb-3">
          Keywords (max 10 selecionadas)
        </p>
        <div className="flex flex-wrap gap-2">
          {rankeandoKeywords.map((kw) => {
            const isActive = selected.includes(kw)
            const color = CHART_COLORS[rankeandoKeywords.indexOf(kw) % CHART_COLORS.length]
            return (
              <button
                key={kw}
                onClick={() => toggleKeyword(kw)}
                className={`font-mono text-[10px] px-2 py-1 rounded border transition-colors ${
                  isActive
                    ? 'border-gray-600 text-gray-100 bg-gray-800'
                    : 'border-gray-800 text-gray-600 hover:text-gray-400'
                }`}
                style={isActive ? { borderColor: color, color } : undefined}
              >
                {kw}
              </button>
            )
          })}
        </div>
      </div>

      {/* Chart */}
      {selected.length === 0 ? (
        <p className="font-mono text-sm text-gray-600 text-center py-8">
          Selecione ao menos uma keyword acima.
        </p>
      ) : (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <ResponsiveContainer width="100%" height={320}>
            <LineChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
              <XAxis
                dataKey="date"
                tick={{ fill: '#4b5563', fontSize: 10, fontFamily: 'monospace' }}
                tickFormatter={d => d.slice(5)}
                axisLine={{ stroke: '#1f2937' }}
                tickLine={false}
              />
              <YAxis
                reversed
                domain={[1, 20]}
                ticks={[1, 5, 10, 15, 20]}
                tick={{ fill: '#4b5563', fontSize: 10, fontFamily: 'monospace' }}
                axisLine={{ stroke: '#1f2937' }}
                tickLine={false}
                width={28}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#111827',
                  border: '1px solid #1f2937',
                  borderRadius: '6px',
                  fontFamily: 'monospace',
                  fontSize: '11px',
                  color: '#d1d5db',
                }}
                labelStyle={{ color: '#9ca3af', marginBottom: '4px' }}
                formatter={(value: unknown) => (value == null ? '—' : `#${value}`)}
              />
              <Legend
                wrapperStyle={{ fontFamily: 'monospace', fontSize: '10px', paddingTop: '8px' }}
              />
              {selected.map((kw) => (
                <Line
                  key={kw}
                  type="monotone"
                  dataKey={kw}
                  stroke={CHART_COLORS[rankeandoKeywords.indexOf(kw) % CHART_COLORS.length]}
                  strokeWidth={1.5}
                  dot={false}
                  connectNulls={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
          <p className="font-mono text-[10px] text-gray-700 mt-2 text-center">
            Posição #1 = topo. Eixo Y invertido. Fonte: SERP quando disponível, SC como fallback.
          </p>
        </div>
      )}
    </div>
  )
}

// ── Formatadores e DeltaPos ──────────────────────────────────────────────────
function fmtBRL(val: number | null | undefined): string {
  if (val == null) return '—'
  return val.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', minimumFractionDigits: 0, maximumFractionDigits: 0 })
}

function fmtNum(val: number | null | undefined): string {
  if (val == null) return '—'
  return val.toLocaleString('pt-BR')
}

function DeltaPos({ delta }: { delta: number | null | undefined }) {
  if (delta == null) return <span className="text-gray-700">—</span>
  if (delta < 0) return <span className="text-emerald-400">↑ {Math.abs(delta)}</span>
  if (delta > 0) return <span className="text-red-400">↓ {delta}</span>
  return <span className="text-gray-600">0</span>
}

// ── Aba Insights ─────────────────────────────────────────────────────────────
function InsightsTab({ keywords }: { keywords: RankingRow[] }) {
  const receitaTotal = keywords
    .filter(k => k.status === 'RANKEANDO')
    .reduce((sum, k) => sum + (k.receita_potencial ?? 0), 0)

  const quickWins = keywords
    .filter(k =>
      k.status === 'RANKEANDO' &&
      k.serp_position != null &&
      k.serp_position >= 11 &&
      k.serp_position <= 20 &&
      (k.sc_impressions_30d ?? 0) > 0
    )
    .sort((a, b) => (b.receita_potencial ?? 0) - (a.receita_potencial ?? 0))
    .slice(0, 5)

  const surpresas = keywords
    .filter(k => k.status === 'SURPRESA' && (k.sc_impressions_30d ?? 0) > 0)
    .sort((a, b) => (b.sc_impressions_30d ?? 0) - (a.sc_impressions_30d ?? 0))
    .slice(0, 5)

  return (
    <div className="space-y-6">
      {/* Card Receita Orgânica Estimada */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
        <p className="font-mono text-[10px] text-gray-600 uppercase tracking-wider mb-1">
          Receita Orgânica Estimada
        </p>
        <p className="font-mono text-2xl text-emerald-400">
          {fmtBRL(receitaTotal)}<span className="text-sm text-gray-600">/mês</span>
        </p>
        <p className="font-mono text-[10px] text-gray-700 mt-1">
          Baseado em CPC × cliques SC 30d · apenas keywords com status RANKEANDO
        </p>
      </div>

      {/* Quick Wins */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-800">
          <p className="font-mono text-[10px] text-gray-600 uppercase tracking-wider">
            Quick Wins — Top {quickWins.length}
          </p>
          <p className="font-mono text-[10px] text-gray-700 mt-0.5">
            Rankeando entre #11–#20 com impressões · ordenado por receita potencial
          </p>
        </div>
        {quickWins.length === 0 ? (
          <p className="font-mono text-xs text-gray-600 text-center py-8">Nenhum quick win identificado.</p>
        ) : (
          <table className="w-full text-xs font-mono">
            <thead>
              <tr className="border-b border-gray-800">
                <th className="px-4 py-2 text-[10px] text-gray-600 uppercase tracking-wider text-left">Keyword</th>
                <th className="px-4 py-2 text-[10px] text-gray-600 uppercase tracking-wider text-right">Pos. Atual</th>
                <th className="px-4 py-2 text-[10px] text-gray-600 uppercase tracking-wider text-right">Δ Pos</th>
                <th className="px-4 py-2 text-[10px] text-gray-600 uppercase tracking-wider text-right">Receita Est.</th>
              </tr>
            </thead>
            <tbody>
              {quickWins.map((row, i) => (
                <tr key={`qw-${i}`} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                  <td className="px-4 py-2 text-gray-100">{row.keyword}</td>
                  <td className="px-4 py-2 text-right text-amber-400">#{row.serp_position}</td>
                  <td className="px-4 py-2 text-right"><DeltaPos delta={row.serp_position_delta} /></td>
                  <td className="px-4 py-2 text-right text-emerald-400">{fmtBRL(row.receita_potencial)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Surpresas com Maior Volume */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-800">
          <p className="font-mono text-[10px] text-gray-600 uppercase tracking-wider">
            Surpresas com Maior Volume
          </p>
          <p className="font-mono text-[10px] text-gray-700 mt-0.5">
            Queries SC sem match no plano · ordenado por impressões
          </p>
        </div>
        {surpresas.length === 0 ? (
          <p className="font-mono text-xs text-gray-600 text-center py-8">Nenhuma surpresa com volume identificada.</p>
        ) : (
          <table className="w-full text-xs font-mono">
            <thead>
              <tr className="border-b border-gray-800">
                <th className="px-4 py-2 text-[10px] text-gray-600 uppercase tracking-wider text-left">Query SC</th>
                <th className="px-4 py-2 text-[10px] text-gray-600 uppercase tracking-wider text-right">Impressões 30d</th>
                <th className="px-4 py-2 text-[10px] text-gray-600 uppercase tracking-wider text-right">CTR</th>
              </tr>
            </thead>
            <tbody>
              {surpresas.map((row, i) => (
                <tr key={`surp-${i}`} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                  <td className="px-4 py-2 text-gray-100">{row.sc_matched_query ?? row.keyword}</td>
                  <td className="px-4 py-2 text-right text-gray-300">{fmtNum(row.sc_impressions_30d)}</td>
                  <td className="px-4 py-2 text-right text-gray-400">
                    {row.sc_ctr_30d != null ? `${(row.sc_ctr_30d * 100).toFixed(1)}%` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

// ── Componente principal ─────────────────────────────────────────────────────
export function ProjetoRanking() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [refreshing, setRefreshing] = useState(false)
  const [queued, setQueued] = useState(false)
  const [sort, setSort] = useState<{ field: SortField; dir: SortDir }>({ field: 'status', dir: 'asc' })
  const [promoteKeyword, setPromoteKeyword] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'table' | 'history' | 'insights'>('table')

  const { data, isLoading, error } = useQuery({
    queryKey: ['ranking', id],
    queryFn: () => rankingApi.get(id!),
    enabled: !!id,
    staleTime: 5 * 60 * 1000,
    refetchInterval: (query) => {
      const status = (query.state.data as { status?: string } | undefined)?.status
      return refreshing && status === 'not_ready' ? 8000 : false
    },
  })

  const { data: overrides = [] } = useQuery({
    queryKey: ['ranking-overrides', id],
    queryFn: () => rankingApi.listOverrides(id!),
    enabled: !!id,
    staleTime: 30_000,
  })

  const overrideMap = useMemo(() =>
    new Map(overrides.map(o => [o.keyword, o])),
    [overrides]
  )

  const upsertMut = useMutation({
    mutationFn: ({ keyword, action, kw_type }: { keyword: string; action: 'promote' | 'block'; kw_type?: string }) =>
      rankingApi.upsertOverride(id!, keyword, action, kw_type),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ranking-overrides', id] })
    },
  })

  const deleteMut = useMutation({
    mutationFn: (keyword: string) => rankingApi.deleteOverride(id!, keyword),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ranking-overrides', id] })
    },
  })

  function handleAction(keyword: string, action: 'promote' | 'block' | 'remove') {
    if (action === 'remove') { deleteMut.mutate(keyword); return }
    if (action === 'promote') { setPromoteKeyword(keyword); return }
    upsertMut.mutate({ keyword, action })
  }

  function handlePromoteConfirm(kw_type: string) {
    if (!promoteKeyword) return
    upsertMut.mutate({ keyword: promoteKeyword, action: 'promote', kw_type })
    setPromoteKeyword(null)
  }

  const allKeywords = data?.keywords ?? []
  const rankeando = allKeywords.filter(k => k.status === 'RANKEANDO').length
  const gap = allKeywords.filter(k => k.status === 'GAP').length
  const surpresa = allKeywords.filter(k => k.status === 'SURPRESA').length
  const rankeandoKeywords = allKeywords
    .filter(k => k.status === 'RANKEANDO')
    .map(k => k.keyword)

  const keywords = useMemo(() => {
    return [...allKeywords].sort((a, b) => {
      const va = sortValue(a, sort.field)
      const vb = sortValue(b, sort.field)
      const cmp = typeof va === 'string' ? va.localeCompare(vb as string) : (va as number) - (vb as number)
      return sort.dir === 'asc' ? cmp : -cmp
    })
  }, [allKeywords, sort])

  useEffect(() => {
    if (refreshing && data?.status === 'ok') setRefreshing(false)
  }, [refreshing, data?.status])

  useEffect(() => {
    if (!queued) return
    const t = setTimeout(() => setQueued(false), 5000)
    return () => clearTimeout(t)
  }, [queued])

  function handleSort(field: SortField) {
    setSort(prev => prev.field === field
      ? { field, dir: prev.dir === 'asc' ? 'desc' : 'asc' }
      : { field, dir: 'asc' })
  }

  async function handleRefresh() {
    if (!id || refreshing) return
    setRefreshing(true)
    try {
      await rankingApi.refresh(id!)
      setQueued(true)
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ['ranking', id] })
        setRefreshing(false)
      }, 90_000)
    } catch { setRefreshing(false) }
  }

  function RefreshButton({ className = '' }: { className?: string }) {
    return (
      <button onClick={handleRefresh} disabled={refreshing}
        className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono
                   bg-violet-500/10 text-violet-400 border border-violet-500/30
                   hover:bg-violet-500/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${className}`}>
        {refreshing ? 'enfileirado…' : 'Atualizar Ranking'}
      </button>
    )
  }

  if (isLoading) return (
    <div className="min-h-full bg-gray-950 flex items-center justify-center">
      <p className="text-gray-500 font-mono text-sm">Carregando ranking...</p>
    </div>
  )

  if (error || !data) return (
    <div className="min-h-full bg-gray-950 flex items-center justify-center">
      <p className="text-red-400 font-mono text-sm">Erro ao carregar ranking.</p>
    </div>
  )

  if (data.status === 'not_ready') return (
    <div className="min-h-full bg-gray-950">
      <div className="max-w-3xl mx-auto px-6 py-16 flex flex-col items-center gap-4 text-center">
        <button onClick={() => navigate(`/projetos/${id}`)} className="text-gray-600 hover:text-gray-400 font-mono text-xs mb-4">
          ← voltar ao projeto
        </button>
        <span className="text-[10px] font-mono bg-amber-500/10 text-amber-400 border border-amber-500/25 px-3 py-1 rounded-full">
          aguardando processamento
        </span>
        <p className="font-mono text-sm text-gray-600">{data.message}</p>
        <RefreshButton />
      </div>
    </div>
  )

  const sh = (label: string, field: SortField, align?: 'left' | 'right') => (
    <SortHeader label={label} field={field} sort={sort} onSort={handleSort} align={align} />
  )

  return (
    <div className="min-h-full bg-gray-950">
      {promoteKeyword && (
        <PromoteModal
          keyword={promoteKeyword}
          onConfirm={handlePromoteConfirm}
          onClose={() => setPromoteKeyword(null)}
        />
      )}
      {queued && (
        <div className="fixed bottom-6 right-6 z-50 font-mono text-xs bg-violet-900/90 text-violet-200 border border-violet-500/40 px-4 py-2.5 rounded-lg shadow-lg">
          Pipeline enfileirado — dados atualizados em ~60s.
        </div>
      )}

      <div className="border-b border-gray-800 bg-gray-900/50">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button onClick={() => navigate(`/projetos/${id}`)} className="text-gray-600 hover:text-gray-400 font-mono text-xs">
              ← projeto
            </button>
            <div>
              <h1 className="font-mono text-sm text-gray-100">{data.projeto_nome}</h1>
              <p className="font-mono text-xs text-gray-600">{data.dominio}</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <RefreshButton />
            <span className="text-[10px] font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 px-2 py-0.5 rounded">{rankeando} rankeando</span>
            <span className="text-[10px] font-mono bg-red-500/10 text-red-400 border border-red-500/30 px-2 py-0.5 rounded">{gap} gap</span>
            {surpresa > 0 && <span className="text-[10px] font-mono bg-amber-500/10 text-amber-400 border border-amber-500/25 px-2 py-0.5 rounded">{surpresa} surpresa</span>}
            {data.updated_at && (
              <span className="text-[10px] font-mono text-gray-600" title={data.updated_at}>
                atualizado {new Date(data.updated_at).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })}
              </span>
            )}
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-6 py-4">
        {/* Tab buttons */}
        <div className="flex gap-2 mb-4 border-b border-gray-800 pb-3">
          <button
            onClick={() => setActiveTab('table')}
            className={`font-mono text-xs px-3 py-1.5 rounded transition-colors ${
              activeTab === 'table'
                ? 'bg-gray-800 text-gray-100 border border-gray-700'
                : 'text-gray-600 hover:text-gray-400'
            }`}
          >
            Tabela
          </button>
          <button
            onClick={() => setActiveTab('history')}
            className={`font-mono text-xs px-3 py-1.5 rounded transition-colors ${
              activeTab === 'history'
                ? 'bg-gray-800 text-gray-100 border border-gray-700'
                : 'text-gray-600 hover:text-gray-400'
            }`}
          >
            Histórico
          </button>
          <button
            onClick={() => setActiveTab('insights')}
            className={`font-mono text-xs px-3 py-1.5 rounded transition-colors ${
              activeTab === 'insights'
                ? 'bg-gray-800 text-gray-100 border border-gray-700'
                : 'text-gray-600 hover:text-gray-400'
            }`}
          >
            Insights
          </button>
        </div>

        {/* Tab content */}
        {activeTab === 'table' ? (
          <>
            {keywords.length === 0 ? (
              <p className="font-mono text-sm text-gray-600 text-center py-16">Nenhuma keyword no ranking ainda.</p>
            ) : (
              <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
                <table className="w-full text-sm font-mono">
                  <thead>
                    <tr className="border-b border-gray-800">
                      {sh('Keyword', 'keyword', 'left')}
                      {sh('Tipo', 'kw_type', 'left')}
                      {sh('Pos. SC', 'sc_position')}
                      {sh('Pos. SRP', 'srp_position')}
                      {sh('Status', 'status', 'left')}
                      {sh('Impressões 30d', 'sc_impressions_30d')}
                      {sh('Cliques 30d', 'sc_clicks_30d')}
                      {sh('Δ Pos', 'srp_position')}
                      {sh('Volume', 'avg_monthly_searches')}
                      {sh('Receita Est.', 'receita_potencial')}
                      <th className="px-4 py-3 w-16" />
                    </tr>
                  </thead>
                  <tbody>
                    {keywords.map((row, i) => {
                      const ov = overrideMap.get(row.keyword)
                      const isBlocked = row.status === 'BLOQUEADO' || ov?.action === 'block'
                      const effectiveStatus = ov?.action === 'promote' ? 'PROMOVIDO'
                        : ov?.action === 'block' ? 'BLOQUEADO'
                        : row.status
                      return (
                        <tr key={`${row.keyword}-${i}`}
                          className={`group border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors ${isBlocked ? 'opacity-40' : ''}`}>
                          <td className="px-4 py-2.5 text-gray-100 text-xs">
                            <span className={isBlocked ? 'line-through' : ''}>{row.keyword}</span>
                            {ov?.action === 'promote' && (
                              <span className="ml-2 text-[10px] text-violet-500">{ov.kw_type}</span>
                            )}
                          </td>
                          <td className="px-4 py-2.5 text-gray-500 text-xs">{row.kw_type ?? '—'}</td>
                          <td className="px-4 py-2.5 text-right text-xs">
                            {row.sc_position_avg_30d != null
                              ? <span className="text-blue-400">{Math.round(row.sc_position_avg_30d)}</span>
                              : <span className="text-gray-700">—</span>}
                          </td>
                          <td className="px-4 py-2.5 text-right text-xs">
                            {row.serp_position != null
                              ? <span className="text-emerald-400">{row.serp_position}</span>
                              : <span className="text-gray-700">—</span>}
                          </td>
                          <td className="px-4 py-2.5"><StatusChip status={effectiveStatus as keyof typeof STATUS_CFG} /></td>
                          <td className="px-4 py-2.5 text-right text-gray-400 text-xs">{row.sc_impressions_30d?.toLocaleString('pt-BR') ?? '—'}</td>
                          <td className="px-4 py-2.5 text-right text-gray-400 text-xs">{row.sc_clicks_30d?.toLocaleString('pt-BR') ?? '—'}</td>
                          <td className="px-4 py-2.5 text-right text-xs">
                            <DeltaPos delta={row.serp_position_delta} />
                          </td>
                          <td className="px-4 py-2.5 text-right text-gray-300 text-xs">
                            {fmtNum(row.avg_monthly_searches)}
                          </td>
                          <td className="px-4 py-2.5 text-right text-emerald-400 text-xs">
                            {fmtBRL(row.receita_potencial)}
                          </td>
                          <td className="px-4 py-2.5 text-right">
                            <RowActions row={row} isOverridden={!!ov} onAction={handleAction} />
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
            <p className="font-mono text-[10px] text-gray-700 mt-3">
              Passe o mouse sobre uma linha para ver as ações. 🚫 bloqueia o SERP · + promove SURPRESA ao plano.
            </p>
          </>
        ) : activeTab === 'history' ? (
          <HistoryChart projetoId={id!} rankeandoKeywords={rankeandoKeywords} />
        ) : (
          <InsightsTab keywords={allKeywords} />
        )}
      </div>
    </div>
  )
}
