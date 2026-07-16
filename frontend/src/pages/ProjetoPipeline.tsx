import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { pipelineApi, projetosApi, type AgentExecution } from '../lib/api'

// ── Config ────────────────────────────────────────────────────────────────────

const AGENT_CFG: Record<string, { label: string; cls: string }> = {
  kw_research:          { label: 'KW Research',       cls: 'text-blue-400 border-blue-500/40' },
  kw_validator:         { label: 'KW Validator',      cls: 'text-amber-400 border-amber-500/40' },
  competitive_intel:    { label: 'Intel Competitiva', cls: 'text-orange-400 border-orange-500/40' },
  rank_intel:           { label: 'Rank Intel',        cls: 'text-indigo-400 border-indigo-500/40' },
  seo_architect:        { label: 'SEO Architect',     cls: 'text-violet-400 border-violet-500/40' },
  seo_content_writer:   { label: 'Content Writer',    cls: 'text-pink-400 border-pink-500/40' },
  seo_content_reviewer: { label: 'Content Reviewer',  cls: 'text-rose-400 border-rose-500/40' },
  site_builder:         { label: 'Site Builder',      cls: 'text-emerald-400 border-emerald-500/40' },
  seo_auditor:          { label: 'SEO Auditor',       cls: 'text-cyan-400 border-cyan-500/40' },
}

const STATUS_CFG: Record<string, { label: string; dot: string }> = {
  pending:     { label: 'Aguardando',  dot: 'bg-gray-600' },
  in_progress: { label: 'Executando', dot: 'bg-amber-400 animate-pulse' },
  completed:   { label: 'Concluído',  dot: 'bg-emerald-400' },
  failed:      { label: 'Falhou',     dot: 'bg-red-400' },
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtDate(dt: string | null): string {
  if (!dt) return '—'
  return new Date(dt).toLocaleString('pt-BR', {
    day: '2-digit', month: '2-digit', year: '2-digit',
    hour: '2-digit', minute: '2-digit',
  })
}

function duration(start: string | null, end: string | null): string {
  if (!start || !end) return ''
  const ms = new Date(end).getTime() - new Date(start).getTime()
  if (ms < 60000) return `${Math.round(ms / 1000)}s`
  return `${Math.round(ms / 60000)}min`
}

// ── Componente ────────────────────────────────────────────────────────────────

export function ProjetoPipeline() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const { data: projeto } = useQuery({
    queryKey: ['projeto', id],
    queryFn: () => projetosApi.get(id!),
    enabled: !!id,
  })

  const { data: executions, isLoading, error } = useQuery({
    queryKey: ['pipeline', id],
    queryFn: () => pipelineApi.get(id!),
    enabled: !!id,
    refetchInterval: 10_000,
  })

  if (isLoading) return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center">
      <p className="text-gray-600 text-sm font-mono">Carregando pipeline...</p>
    </div>
  )

  if (error || !executions) return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center">
      <p className="text-red-400 text-sm font-mono">Erro ao carregar pipeline.</p>
    </div>
  )

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
          <span className="font-mono font-semibold text-gray-100">
            Pipeline de Agentes
          </span>
          {projeto && (
            <span className="text-xs font-mono text-gray-600">{projeto.projeto_nome}</span>
          )}
          <span className="ml-auto text-[10px] font-mono text-gray-700">atualiza a cada 10s</span>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-8">
        {executions.length === 0 ? (
          <div className="bg-gray-900 border border-gray-800 rounded-lg p-8 text-center">
            <p className="text-gray-600 text-sm font-mono">
              Nenhuma execução de agente registrada para este projeto.
            </p>
            <p className="text-gray-700 text-xs font-mono mt-2">
              O pipeline inicia automaticamente quando o projeto é publicado.
            </p>
          </div>
        ) : (
          <div className="relative">
            {/* Linha vertical conectora */}
            <div className="absolute left-[19px] top-4 bottom-4 w-px bg-gray-800" />

            <div className="space-y-4">
              {executions.map((exec: AgentExecution, i: number) => {
                const agentCfg = AGENT_CFG[exec.agent_name] ?? { label: exec.agent_name, cls: 'text-gray-400 border-gray-600' }
                const statusCfg = STATUS_CFG[exec.status] ?? { label: exec.status, dot: 'bg-gray-600' }
                const dur = duration(exec.started_at, exec.completed_at)

                return (
                  <div key={exec.id} className="relative flex gap-4">
                    {/* Dot na linha do tempo */}
                    <div className="relative z-10 mt-3.5">
                      <div className={`w-2.5 h-2.5 rounded-full ${statusCfg.dot}`} />
                    </div>

                    {/* Card */}
                    <div className={`flex-1 bg-gray-900 border rounded-lg p-4 ${exec.status === 'failed' ? 'border-red-500/30' : 'border-gray-800'}`}>
                      <div className="flex items-start justify-between gap-4 flex-wrap">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className={`text-xs font-mono font-semibold px-2 py-0.5 rounded border bg-transparent ${agentCfg.cls}`}>
                            {agentCfg.label}
                          </span>
                          <span className="text-[10px] font-mono text-gray-600">
                            #{i + 1} · id {exec.id}
                          </span>
                        </div>
                        <div className="flex items-center gap-3">
                          {dur && (
                            <span className="text-[10px] font-mono text-gray-600">{dur}</span>
                          )}
                          <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${
                            exec.status === 'completed' ? 'text-emerald-400 bg-emerald-500/10' :
                            exec.status === 'failed'    ? 'text-red-400 bg-red-500/10' :
                            exec.status === 'in_progress' ? 'text-amber-400 bg-amber-500/10' :
                            'text-gray-500 bg-gray-800'
                          }`}>
                            {statusCfg.label}
                          </span>
                        </div>
                      </div>

                      <div className="mt-2 grid grid-cols-2 gap-x-6 gap-y-0.5">
                        <p className="text-[10px] font-mono text-gray-600">
                          início: <span className="text-gray-500">{fmtDate(exec.started_at)}</span>
                        </p>
                        {exec.completed_at && (
                          <p className="text-[10px] font-mono text-gray-600">
                            fim: <span className="text-gray-500">{fmtDate(exec.completed_at)}</span>
                          </p>
                        )}
                        {exec.triggered_at && (
                          <p className="text-[10px] font-mono text-gray-600">
                            enfileirado: <span className="text-gray-500">{fmtDate(exec.triggered_at)}</span>
                          </p>
                        )}
                      </div>

                      {exec.status === 'failed' && exec.error_message && (
                        <div className="mt-3 bg-red-500/5 border border-red-500/20 rounded p-2">
                          <p className="text-[10px] font-mono text-red-400 leading-relaxed whitespace-pre-wrap break-all">
                            {exec.error_message}
                          </p>
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
