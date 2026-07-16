import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { auditApi, projetosApi, type AuditData } from '../lib/api'

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtDate(dt: string | null | undefined): string {
  if (!dt) return '—'
  return new Date(dt).toLocaleString('pt-BR', {
    day: '2-digit', month: '2-digit', year: '2-digit',
    hour: '2-digit', minute: '2-digit',
  })
}

function PerfBadge({ value }: { value: number | null | undefined }) {
  if (value == null) return <span className="text-gray-600 font-mono text-sm">N/A</span>
  const cls = value >= 90 ? 'text-emerald-400' : value >= 50 ? 'text-amber-400' : 'text-red-400'
  const label = value >= 90 ? 'Bom' : value >= 50 ? 'Melhorar' : 'Ruim'
  return (
    <span className={`font-mono text-2xl font-bold ${cls}`}>
      {value}<span className="text-base font-normal text-gray-600">/100</span>
      <span className={`ml-2 text-xs font-normal ${cls}`}>{label}</span>
    </span>
  )
}

function MetricRow({ label, value, unit, thresholds }: {
  label: string
  value: number | null | undefined
  unit: string
  thresholds: [number, number]  // [good, ok]
}) {
  const icon = value == null ? '—' :
    value <= thresholds[0] ? '✅' :
    value <= thresholds[1] ? '⚠️' : '❌'

  const cls = value == null ? 'text-gray-600' :
    value <= thresholds[0] ? 'text-emerald-400' :
    value <= thresholds[1] ? 'text-amber-400' : 'text-red-400'

  return (
    <div className="flex items-center justify-between py-2.5 border-b border-gray-800 last:border-0">
      <span className="text-xs font-mono text-gray-500">{label}</span>
      <span className={`text-sm font-mono font-semibold ${cls}`}>
        {icon} {value != null ? `${value.toLocaleString('pt-BR')}${unit}` : '—'}
      </span>
    </div>
  )
}

function SchemaRow({ label, valid, missingFields }: {
  label: string
  valid: boolean
  missingFields: string[]
}) {
  return (
    <div className="py-2.5 border-b border-gray-800 last:border-0">
      <div className="flex items-center justify-between">
        <span className="text-xs font-mono text-gray-500">{label}</span>
        <span className={`text-sm font-mono font-semibold ${valid ? 'text-emerald-400' : 'text-red-400'}`}>
          {valid ? '✅ válido' : '❌ inválido'}
        </span>
      </div>
      {!valid && missingFields.length > 0 && (
        <p className="text-[10px] font-mono text-red-400/70 mt-1">
          campos ausentes: {missingFields.join(', ')}
        </p>
      )}
    </div>
  )
}

// ── Componente ────────────────────────────────────────────────────────────────

export function SeoAuditoria() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const { data: projeto } = useQuery({
    queryKey: ['projeto', id],
    queryFn: () => projetosApi.get(id!),
    enabled: !!id,
  })

  const { data: audit, isLoading, error } = useQuery({
    queryKey: ['audit', id],
    queryFn: () => auditApi.get(id!),
    enabled: !!id,
  })

  if (isLoading) return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center">
      <p className="text-gray-600 text-sm font-mono">Carregando auditoria...</p>
    </div>
  )

  if (error) return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center">
      <p className="text-red-400 text-sm font-mono">Erro ao carregar dados da auditoria.</p>
    </div>
  )

  const isNotFound = !audit || audit.status === 'not_found'
  const data = audit?.data as AuditData | undefined

  return (
    <div className="min-h-screen bg-gray-950">
      <header className="sticky top-0 z-10 bg-gray-950/95 backdrop-blur border-b border-gray-800 px-6 py-3.5">
        <div className="max-w-3xl mx-auto flex items-center gap-4">
          <button
            onClick={() => navigate(`/projetos/${id}`)}
            className="font-mono text-sm text-gray-600 hover:text-gray-300 transition-colors"
          >
            ← voltar
          </button>
          <div className="h-4 w-px bg-gray-800" />
          <span className="font-mono font-semibold text-gray-100">Auditoria SEO</span>
          {projeto && (
            <span className="text-xs font-mono text-gray-600">{projeto.projeto_nome}</span>
          )}
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-8 space-y-6">

        {isNotFound ? (
          <div className="bg-gray-900 border border-gray-800 rounded-lg p-8 text-center">
            <p className="text-gray-500 text-sm font-mono mb-2">Nenhuma auditoria encontrada.</p>
            <p className="text-gray-700 text-xs font-mono">
              A auditoria é executada automaticamente após o site ser publicado pelo AGENT-011.
            </p>
          </div>
        ) : (
          <>
            {/* Status e datas */}
            <section className="bg-gray-900 border border-gray-800 rounded-lg p-5">
              <div className="flex items-center justify-between flex-wrap gap-3">
                <div>
                  <p className="text-[10px] font-mono text-gray-600 uppercase tracking-wider mb-0.5">URL auditada</p>
                  <p className="text-sm font-mono text-gray-300 break-all">{data?.target_url ?? '—'}</p>
                </div>
                <span className={`text-xs font-mono px-2 py-1 rounded border ${
                  audit.status === 'completed' ? 'text-emerald-400 border-emerald-500/30 bg-emerald-500/10' :
                  audit.status === 'failed'    ? 'text-red-400 border-red-500/30 bg-red-500/10' :
                  'text-amber-400 border-amber-500/30 bg-amber-500/10'
                }`}>
                  {audit.status}
                </span>
              </div>
              <div className="mt-3 flex gap-6 flex-wrap">
                <div>
                  <p className="text-[10px] font-mono text-gray-600">iniciado</p>
                  <p className="text-xs font-mono text-gray-400">{fmtDate(audit.started_at)}</p>
                </div>
                {audit.completed_at && (
                  <div>
                    <p className="text-[10px] font-mono text-gray-600">concluído</p>
                    <p className="text-xs font-mono text-gray-400">{fmtDate(audit.completed_at)}</p>
                  </div>
                )}
              </div>
            </section>

            {data && (
              <>
                {/* Performance */}
                <section className="bg-gray-900 border border-gray-800 rounded-lg p-5">
                  <h2 className="text-xs font-mono font-semibold uppercase tracking-wider text-gray-600 mb-4">
                    Performance — PageSpeed Insights
                  </h2>
                  <div className="mb-4">
                    <p className="text-[10px] font-mono text-gray-600 mb-1">Score</p>
                    <PerfBadge value={data.scores?.performance} />
                  </div>
                  <div>
                    <p className="text-[10px] font-mono text-gray-600 uppercase tracking-wider mb-1">Core Web Vitals</p>
                    <MetricRow
                      label="LCP — Largest Contentful Paint"
                      value={data.scores?.cwv?.lcp_ms}
                      unit="ms"
                      thresholds={[2500, 4000]}
                    />
                    <MetricRow
                      label="CLS — Cumulative Layout Shift"
                      value={data.scores?.cwv?.cls != null ? Math.round(data.scores.cwv.cls * 1000) / 1000 : null}
                      unit=""
                      thresholds={[0.1, 0.25]}
                    />
                    <MetricRow
                      label="TBT — Total Blocking Time"
                      value={data.scores?.cwv?.tbt_ms}
                      unit="ms"
                      thresholds={[200, 600]}
                    />
                  </div>
                </section>

                {/* Schema JSON-LD */}
                <section className="bg-gray-900 border border-gray-800 rounded-lg p-5">
                  <h2 className="text-xs font-mono font-semibold uppercase tracking-wider text-gray-600 mb-4">
                    Validação JSON-LD
                  </h2>
                  <SchemaRow
                    label="LocalBusiness Schema"
                    valid={data.schema_validation?.local_business?.valid ?? false}
                    missingFields={data.schema_validation?.local_business?.missing_fields ?? []}
                  />
                  <SchemaRow
                    label="Service Schema"
                    valid={data.schema_validation?.service?.valid ?? false}
                    missingFields={data.schema_validation?.service?.missing_fields ?? []}
                  />
                </section>

                {/* Canibalização */}
                <section className="bg-gray-900 border border-gray-800 rounded-lg p-5">
                  <h2 className="text-xs font-mono font-semibold uppercase tracking-wider text-gray-600 mb-3">
                    Canibalização de Keywords
                  </h2>
                  {data.cannibalization?.found ? (
                    <>
                      <p className="text-xs font-mono text-amber-400 mb-3">
                        ⚠️ {data.cannibalization.pairs?.length ?? 0} par(es) detectado(s)
                      </p>
                      <div className="space-y-2">
                        {(data.cannibalization.pairs ?? []).map((pair: unknown, i: number) => (
                          <div key={i} className="bg-amber-500/5 border border-amber-500/20 rounded p-2.5">
                            <p className="text-[11px] font-mono text-amber-300 break-all">
                              {typeof pair === 'object' && pair !== null ? JSON.stringify(pair) : String(pair)}
                            </p>
                          </div>
                        ))}
                      </div>
                    </>
                  ) : (
                    <p className="text-xs font-mono text-emerald-400">✅ Nenhuma canibalização detectada</p>
                  )}
                </section>

                {/* Top Ações */}
                {data.top_actions && data.top_actions.length > 0 && (
                  <section className="bg-gray-900 border border-gray-800 rounded-lg p-5">
                    <h2 className="text-xs font-mono font-semibold uppercase tracking-wider text-gray-600 mb-3">
                      Top Ações Prioritárias
                    </h2>
                    <ol className="space-y-2">
                      {data.top_actions.map((action: string, i: number) => (
                        <li key={i} className="flex gap-3 text-sm font-mono text-gray-300">
                          <span className="text-gray-600 shrink-0">{i + 1}.</span>
                          <span>{action}</span>
                        </li>
                      ))}
                    </ol>
                  </section>
                )}

                {/* Findings */}
                {data.findings && data.findings.length > 0 && (
                  <section className="bg-gray-900 border border-gray-800 rounded-lg p-5">
                    <h2 className="text-xs font-mono font-semibold uppercase tracking-wider text-gray-600 mb-3">
                      Oportunidades e Diagnósticos
                      <span className="ml-2 text-gray-700 normal-case font-normal">({data.findings.length})</span>
                    </h2>
                    <div className="space-y-0">
                      {data.findings.map((finding: unknown, i: number) => {
                        if (typeof finding === 'string') {
                          return (
                            <div key={i} className="text-xs font-mono text-gray-400 py-2 border-b border-gray-800/50 last:border-0">
                              {finding}
                            </div>
                          )
                        }
                        const f = finding as { severity?: string; message?: string; action?: string; category?: string }
                        const severityIcon = f.severity === 'critical' ? '❌' : f.severity === 'warning' ? '⚠️' : 'ℹ️'
                        const msgCls = f.severity === 'critical' ? 'text-red-300' : f.severity === 'warning' ? 'text-amber-300' : 'text-gray-300'
                        return (
                          <div key={i} className="py-3 border-b border-gray-800/50 last:border-0">
                            <div className="flex gap-2 items-start">
                              <span className="text-sm shrink-0 mt-0.5">{severityIcon}</span>
                              <div className="min-w-0">
                                <p className={`text-xs font-mono font-medium ${msgCls} leading-snug`}>
                                  {f.message ?? String(finding)}
                                </p>
                                {f.action && (
                                  <p className="text-[11px] font-mono text-gray-600 mt-0.5 leading-snug">
                                    → {f.action}
                                  </p>
                                )}
                              </div>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </section>
                )}
              </>
            )}
          </>
        )}
      </main>
    </div>
  )
}
