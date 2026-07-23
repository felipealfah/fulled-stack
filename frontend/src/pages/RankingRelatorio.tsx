import type { ReactNode } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { rankingApi } from '../lib/api'

// ── Sub-componentes internos ───────────────────────────────────────────────

interface SummaryCardProps {
  label: string
  count: number
  delta: number | null
  /** Semântica do delta: 'positive-up' (↑ é bom), 'positive-down' (↓ é bom) */
  deltaSemantics: 'positive-up' | 'positive-down'
}

function SummaryCard({ label, count, delta, deltaSemantics }: SummaryCardProps) {
  const isPositive = delta === null
    ? null
    : deltaSemantics === 'positive-up'
      ? delta > 0
      : delta < 0

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 flex flex-col gap-1">
      <span className="text-xs font-mono text-gray-500 uppercase tracking-wider">{label}</span>
      <span className="text-3xl font-mono font-bold text-gray-100">{count}</span>
      {delta !== null && (
        <span className={`text-xs font-mono ${
          isPositive ? 'text-emerald-400' : delta === 0 ? 'text-gray-500' : 'text-red-400'
        }`}>
          {delta > 0 ? `↑ +${delta}` : delta < 0 ? `↓ ${delta}` : '→ 0'} vs anterior
        </span>
      )}
      {delta === null && (
        <span className="text-xs font-mono text-gray-600">— baseline</span>
      )}
    </div>
  )
}

interface SectionProps {
  title: string
  children: ReactNode
  hidden?: boolean
}

function Section({ title, children, hidden }: SectionProps) {
  if (hidden) return null
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-800">
        <h2 className="text-sm font-mono font-semibold text-gray-300">{title}</h2>
      </div>
      <div>{children}</div>
    </div>
  )
}

// ── Componente principal ───────────────────────────────────────────────────

export function RankingRelatorio() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const projetoId = id!

  const { data, isLoading, isError } = useQuery({
    queryKey: ['ranking-report', id],
    queryFn: () => rankingApi.report(projetoId),
    enabled: !!id,
    staleTime: 5 * 60 * 1000, // 5 min — relatório não muda frequentemente
  })

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center">
        <span className="font-mono text-gray-400 text-sm animate-pulse">Carregando relatório...</span>
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center">
        <div className="bg-gray-900 border border-red-500/30 rounded-lg p-6 max-w-md text-center">
          <p className="font-mono text-red-400 text-sm">Erro ao carregar relatório</p>
          <button onClick={() => navigate(`/projetos/${id}`)} className="mt-4 text-xs font-mono text-gray-500 hover:text-gray-300">
            ← Voltar ao projeto
          </button>
        </div>
      </div>
    )
  }

  // Estado not_ready
  if (data.status === 'not_ready') {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center">
        <div className="bg-gray-900 border border-amber-500/30 rounded-lg p-6 max-w-md text-center space-y-3">
          <p className="font-mono text-amber-400 text-sm font-semibold">Histórico não disponível</p>
          <p className="font-mono text-gray-400 text-xs leading-relaxed">{data.message}</p>
          <button onClick={() => navigate(`/projetos/${id}`)} className="mt-4 text-xs font-mono text-gray-500 hover:text-gray-300">
            ← Voltar ao projeto
          </button>
        </div>
      </div>
    )
  }

  // Estados baseline e weekly
  const { mode, summary, current_snapshot_date, previous_snapshot_date,
          top_rankeando = [], fell = [], rose = [], new_surpresa = [], critical_gaps = [] } = data

  const modeBadge = mode === 'weekly'
    ? <span className="px-2 py-0.5 rounded text-xs font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">Semanal</span>
    : <span className="px-2 py-0.5 rounded text-xs font-mono bg-gray-500/10 text-gray-400 border border-gray-700">Baseline</span>

  const dateRange = mode === 'weekly' && previous_snapshot_date
    ? `${previous_snapshot_date} → ${current_snapshot_date}`
    : `Baseline: ${current_snapshot_date}`

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 p-6 space-y-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-3">
            <h1 className="text-lg font-mono font-bold text-gray-100">Relatório de Ranking</h1>
            {modeBadge}
          </div>
          <p className="text-xs font-mono text-gray-500">{dateRange}</p>
        </div>
        <button
          onClick={() => navigate(`/projetos/${id}`)}
          className="text-xs font-mono text-gray-500 hover:text-gray-300 transition-colors"
        >
          ← Voltar ao projeto
        </button>
      </div>

      {/* Summary Cards */}
      {summary && (
        <div className="grid grid-cols-3 gap-4">
          <SummaryCard
            label="Rankeando"
            count={summary.rankeando}
            delta={summary.rankeando_delta}
            deltaSemantics="positive-up"
          />
          <SummaryCard
            label="GAP"
            count={summary.gap}
            delta={summary.gap_delta}
            deltaSemantics="positive-down"
          />
          <SummaryCard
            label="SURPRESA"
            count={summary.surpresa}
            delta={summary.surpresa_delta}
            deltaSemantics="positive-up"
          />
        </div>
      )}

      {/* Melhores Posições */}
      <Section title="🏆 Melhores Posições" hidden={top_rankeando.length === 0}>
        <table className="w-full">
          <thead>
            <tr className="text-xs font-mono text-gray-500 border-b border-gray-800">
              <th className="py-2 px-3 text-left">Keyword</th>
              <th className="py-2 px-3 text-right">SERP</th>
              <th className="py-2 px-3 text-right">SC Pos</th>
              <th className="py-2 px-3 text-right">Impressões 7d</th>
            </tr>
          </thead>
          <tbody>
            {top_rankeando.map((r, i) => (
              <tr key={i} className="border-b border-gray-800 hover:bg-gray-800/30">
                <td className="py-2 px-3 text-xs font-mono text-gray-200">{r.keyword}</td>
                <td className="py-2 px-3 text-xs font-mono text-emerald-400 text-right">#{r.serp_position ?? '—'}</td>
                <td className="py-2 px-3 text-xs font-mono text-gray-400 text-right">{r.sc_position?.toFixed(1) ?? '—'}</td>
                <td className="py-2 px-3 text-xs font-mono text-gray-400 text-right">{r.sc_impressions_30d ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      {/* Quedas — weekly only, hidden if empty */}
      <Section title="📉 Quedas de Posição" hidden={mode !== 'weekly' || fell.length === 0}>
        <table className="w-full">
          <thead>
            <tr className="text-xs font-mono text-gray-500 border-b border-gray-800">
              <th className="py-2 px-3 text-left">Keyword</th>
              <th className="py-2 px-3 text-right">Anterior</th>
              <th className="py-2 px-3 text-right">Atual</th>
              <th className="py-2 px-3 text-right">Delta</th>
            </tr>
          </thead>
          <tbody>
            {fell.map((r, i) => (
              <tr key={i} className="border-b border-gray-800 hover:bg-gray-800/30">
                <td className="py-2 px-3 text-xs font-mono text-gray-200">{r.keyword}</td>
                <td className="py-2 px-3 text-xs font-mono text-gray-400 text-right">#{r.prev_serp ?? '—'}</td>
                <td className="py-2 px-3 text-xs font-mono text-gray-400 text-right">#{r.curr_serp ?? '—'}</td>
                <td className="py-2 px-3 text-xs font-mono text-red-400 text-right">+{r.delta} ↓</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      {/* Subidas — weekly only, hidden if empty */}
      <Section title="📈 Subidas de Posição" hidden={mode !== 'weekly' || rose.length === 0}>
        <table className="w-full">
          <thead>
            <tr className="text-xs font-mono text-gray-500 border-b border-gray-800">
              <th className="py-2 px-3 text-left">Keyword</th>
              <th className="py-2 px-3 text-right">Anterior</th>
              <th className="py-2 px-3 text-right">Atual</th>
              <th className="py-2 px-3 text-right">Delta</th>
            </tr>
          </thead>
          <tbody>
            {rose.map((r, i) => (
              <tr key={i} className="border-b border-gray-800 hover:bg-gray-800/30">
                <td className="py-2 px-3 text-xs font-mono text-gray-200">{r.keyword}</td>
                <td className="py-2 px-3 text-xs font-mono text-gray-400 text-right">#{r.prev_serp ?? '—'}</td>
                <td className="py-2 px-3 text-xs font-mono text-gray-400 text-right">#{r.curr_serp ?? '—'}</td>
                <td className="py-2 px-3 text-xs font-mono text-emerald-400 text-right">{r.delta} ↑</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      {/* Novas SURPRESAs — weekly only, hidden if empty */}
      <Section title="✨ Novas SURPRESAs" hidden={mode !== 'weekly' || new_surpresa.length === 0}>
        <table className="w-full">
          <thead>
            <tr className="text-xs font-mono text-gray-500 border-b border-gray-800">
              <th className="py-2 px-3 text-left">Keyword</th>
              <th className="py-2 px-3 text-right">Impressões 7d</th>
            </tr>
          </thead>
          <tbody>
            {new_surpresa.map((r, i) => (
              <tr key={i} className="border-b border-gray-800 hover:bg-gray-800/30">
                <td className="py-2 px-3 text-xs font-mono text-gray-200">{r.keyword}</td>
                <td className="py-2 px-3 text-xs font-mono text-purple-400 text-right">{r.sc_impressions_30d ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      {/* GAPs Críticos — always shown */}
      <Section title="⚠️ GAPs Críticos">
        {critical_gaps.length === 0 ? (
          <p className="py-4 px-3 text-xs font-mono text-gray-600 text-center">Nenhum gap crítico</p>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="text-xs font-mono text-gray-500 border-b border-gray-800">
                <th className="py-2 px-3 text-left">Keyword</th>
                <th className="py-2 px-3 text-left">Status</th>
                <th className="py-2 px-3 text-right">SC Pos</th>
                <th className="py-2 px-3 text-right">Impressões 7d</th>
              </tr>
            </thead>
            <tbody>
              {critical_gaps.map((r, i) => (
                <tr key={i} className="border-b border-gray-800 hover:bg-gray-800/30">
                  <td className="py-2 px-3 text-xs font-mono text-gray-200">{r.keyword}</td>
                  <td className="py-2 px-3 text-xs font-mono">
                    <span className="px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/30">
                      {r.status}
                    </span>
                  </td>
                  <td className="py-2 px-3 text-xs font-mono text-gray-400 text-right">{r.sc_position?.toFixed(1) ?? '—'}</td>
                  <td className="py-2 px-3 text-xs font-mono text-amber-400 text-right">{r.sc_impressions_30d ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>
    </div>
  )
}
