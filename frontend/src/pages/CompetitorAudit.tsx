import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { competitorAuditApi, type CompetitorInfo } from '../lib/api'

// ── Helpers ───────────────────────────────────────────────────────────────

function fmtDate(iso: string | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('pt-BR', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

function Tag({ children, cls }: { children: React.ReactNode; cls: string }) {
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded border text-[10px] font-mono ${cls}`}>
      {children}
    </span>
  )
}

// ── Linha de concorrente ──────────────────────────────────────────────────

function CompetitorRow({ c }: { c: CompetitorInfo }) {
  const age = c.domain_age_years != null ? `${c.domain_age_years}a` : '—'
  const backlinks = c.backlink_count != null ? String(c.backlink_count) : 'N/A'
  const schemas = c.schema_json_ld.length > 0 ? c.schema_json_ld.join(', ') : '—'

  const sections = Object.entries(c.sections_detected ?? {})
    .filter(([, v]) => v)
    .map(([k]) => k)

  const trust = c.trust_signals ?? {}

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-5 space-y-4">
      {/* Cabeçalho */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <a
            href={c.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm font-mono text-gray-100 hover:text-white transition-colors"
          >
            {c.domain} ↗
          </a>
          {c.title_tag && (
            <p className="text-[11px] font-mono text-gray-500 mt-0.5 truncate max-w-lg">{c.title_tag}</p>
          )}
        </div>
        <Tag cls="bg-slate-500/10 text-slate-400 border-slate-500/30">#{c.position}</Tag>
      </div>

      {/* Métricas principais */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="bg-gray-950 rounded p-3">
          <p className="text-[10px] font-mono uppercase tracking-wider text-gray-600">Domínio (idade)</p>
          <p className="text-sm font-mono text-gray-100 mt-1">{age}</p>
          {c.domain_created_date && (
            <p className="text-[10px] font-mono text-gray-600">{c.domain_created_date}</p>
          )}
        </div>
        <div className="bg-gray-950 rounded p-3">
          <p className="text-[10px] font-mono uppercase tracking-wider text-gray-600">Palavras</p>
          <p className="text-sm font-mono text-gray-100 mt-1">{c.estimated_word_count.toLocaleString('pt-BR')}</p>
        </div>
        <div className="bg-gray-950 rounded p-3">
          <p className="text-[10px] font-mono uppercase tracking-wider text-gray-600">Geo-pages</p>
          <p className="text-sm font-mono text-gray-100 mt-1">{c.geo_pages_count}</p>
        </div>
        <div className="bg-gray-950 rounded p-3">
          <p className="text-[10px] font-mono uppercase tracking-wider text-gray-600">Backlinks (dofollow)</p>
          <p className={`text-sm font-mono mt-1 ${c.backlink_count != null ? 'text-gray-100' : 'text-gray-600'}`}>
            {backlinks}
          </p>
        </div>
      </div>

      {/* H1 e H2s */}
      {c.h1 && (
        <div>
          <p className="text-[10px] font-mono uppercase tracking-wider text-gray-600 mb-1">H1</p>
          <p className="text-xs font-mono text-gray-300">{c.h1}</p>
        </div>
      )}
      {c.h2s.length > 0 && (
        <div>
          <p className="text-[10px] font-mono uppercase tracking-wider text-gray-600 mb-2">H2s</p>
          <div className="flex flex-wrap gap-1">
            {c.h2s.map((h, i) => (
              <span key={i} className="text-[10px] font-mono bg-gray-800 border border-gray-700 rounded px-2 py-0.5 text-gray-400">
                {h}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Seções detectadas + trust signals */}
      <div className="flex flex-wrap gap-2 pt-1 border-t border-gray-800">
        {sections.map(s => (
          <Tag key={s} cls="bg-blue-500/10 text-blue-400 border-blue-500/30">{s}</Tag>
        ))}
        {trust.has_testimonials && <Tag cls="bg-emerald-500/10 text-emerald-400 border-emerald-500/30">depoimentos</Tag>}
        {trust.has_faq && <Tag cls="bg-emerald-500/10 text-emerald-400 border-emerald-500/30">FAQ</Tag>}
        {trust.has_cnpj && <Tag cls="bg-emerald-500/10 text-emerald-400 border-emerald-500/30">CNPJ</Tag>}
        {trust.has_google_maps && <Tag cls="bg-emerald-500/10 text-emerald-400 border-emerald-500/30">Google Maps</Tag>}
        {trust.certifications_mentioned && <Tag cls="bg-emerald-500/10 text-emerald-400 border-emerald-500/30">certificações</Tag>}
        {c.seo_plugin_detected && (
          <Tag cls="bg-violet-500/10 text-violet-400 border-violet-500/30">{c.seo_plugin_detected}</Tag>
        )}
      </div>

      {/* Schema */}
      {schemas !== '—' && (
        <div>
          <p className="text-[10px] font-mono uppercase tracking-wider text-gray-600 mb-1">Schema JSON-LD</p>
          <p className="text-xs font-mono text-gray-400">{schemas}</p>
        </div>
      )}
    </div>
  )
}

// ── Componente principal ──────────────────────────────────────────────────

export function CompetitorAudit() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const { data, isLoading, isError } = useQuery({
    queryKey: ['competitor-audit', id],
    queryFn: () => competitorAuditApi.get(id!),
    retry: false,
  })

  if (isLoading) {
    return (
      <div className="min-h-full bg-gray-950 flex items-center justify-center">
        <p className="text-gray-500 font-mono text-sm">Carregando auditoria de concorrentes...</p>
      </div>
    )
  }

  if (isError || !data || data.status === 'not_found') {
    return (
      <div className="min-h-full bg-gray-950 flex items-center justify-center">
        <div className="text-center space-y-3">
          <p className="text-gray-400 font-mono text-sm">Auditoria de concorrentes não encontrada.</p>
          <p className="text-gray-600 font-mono text-xs">Acione o agente no Claude Code CLI:</p>
          <code className="block bg-gray-900 border border-gray-800 rounded-lg px-4 py-2 text-emerald-400 font-mono text-sm">
            /competitor-audit {id}
          </code>
        </div>
      </div>
    )
  }

  const gaps = data.market_gaps!
  const competitors = data.competitors ?? []

  return (
    <div className="min-h-full bg-gray-950">
      {/* Header */}
      <div className="sticky top-0 z-10 border-b border-gray-800 bg-gray-900/50 backdrop-blur-sm">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button
              onClick={() => navigate(`/projetos/${id}`)}
              className="text-gray-600 hover:text-gray-400 font-mono text-xs transition-colors"
            >
              ← projeto
            </button>
            <div>
              <h1 className="font-mono text-sm font-semibold text-gray-100">
                Auditoria de Concorrentes
              </h1>
              <span className="text-[10px] font-mono text-gray-600">
                {data.keyword_principal} · {fmtDate(data.generated_at)}
              </span>
            </div>
          </div>
          <Tag cls="bg-orange-500/10 text-orange-400 border-orange-500/30">
            {competitors.length} concorrente{competitors.length !== 1 ? 's' : ''}
          </Tag>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-6 py-6 space-y-6">

        {/* Market Gaps */}
        <section className="bg-gray-900 border border-gray-800 rounded-lg p-5">
          <h2 className="text-xs font-mono font-semibold uppercase tracking-wider text-gray-600 mb-4">
            Market Gaps — oportunidades identificadas
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-mono text-gray-500">Benchmark palavras/página</span>
                <span className="text-[11px] font-mono text-amber-400 font-semibold">
                  {gaps.benchmark_word_count?.toLocaleString('pt-BR')} palavras
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-mono text-gray-500">Geo-pages benchmark</span>
                <span className="text-[11px] font-mono text-gray-300">{gaps.geo_pages_benchmark}</span>
              </div>
              {gaps.backlink_benchmark != null && (
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-mono text-gray-500">Backlinks benchmark (dofollow)</span>
                  <span className="text-[11px] font-mono text-gray-300">{gaps.backlink_benchmark}</span>
                </div>
              )}
            </div>
            <div className="space-y-2">
              {gaps.schema_missing.length > 0 && (
                <div>
                  <p className="text-[10px] font-mono uppercase tracking-wider text-gray-600 mb-1">
                    Schemas ausentes (oportunidade)
                  </p>
                  <div className="flex flex-wrap gap-1">
                    {gaps.schema_missing.map(s => (
                      <Tag key={s} cls="bg-emerald-500/10 text-emerald-400 border-emerald-500/30">{s}</Tag>
                    ))}
                  </div>
                </div>
              )}
              {gaps.required_sections.length > 0 && (
                <div>
                  <p className="text-[10px] font-mono uppercase tracking-wider text-gray-600 mb-1">
                    Seções obrigatórias
                  </p>
                  <div className="flex flex-wrap gap-1">
                    {gaps.required_sections.map(s => (
                      <Tag key={s} cls="bg-blue-500/10 text-blue-400 border-blue-500/30">{s}</Tag>
                    ))}
                  </div>
                </div>
              )}
              {gaps.trust_gaps.length > 0 && (
                <div>
                  <p className="text-[10px] font-mono uppercase tracking-wider text-gray-600 mb-1">
                    Trust gaps
                  </p>
                  <div className="flex flex-wrap gap-1">
                    {gaps.trust_gaps.map(s => (
                      <Tag key={s} cls="bg-amber-500/10 text-amber-400 border-amber-500/30">{s}</Tag>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
          {gaps.summary && (
            <p className="mt-4 text-xs font-mono text-gray-400 border-t border-gray-800 pt-3">
              {gaps.summary}
            </p>
          )}
        </section>

        {/* Concorrentes */}
        <div>
          <h2 className="text-xs font-mono font-semibold uppercase tracking-wider text-gray-600 mb-3">
            Concorrentes analisados
          </h2>
          <div className="space-y-4">
            {competitors.map((c, i) => (
              <CompetitorRow key={c.domain ?? i} c={c} />
            ))}
          </div>
        </div>

      </div>
    </div>
  )
}
