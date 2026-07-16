import { useState, useRef, useCallback, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'
import { seoPlanApi, geoTargetsApi, type SeoPlan as SeoPlanType, type SeoPlanPage, type SeoPlanKeyword, type GeoTarget, type GeoTargetCreate, type RegionIntel } from '../lib/api'

// ── Constantes ────────────────────────────────────────────────────────────

const GEO_TERMS = [
  'brasilia', 'brasília', 'df', 'distrito federal',
  'gama', 'taguatinga', 'ceilândia', 'ceilandia',
  'sobradinho', 'planaltina', 'guará', 'guara',
  'cruzeiro', 'lago sul', 'lago norte', 'asa norte', 'asa sul',
  'samambaia', 'aguas claras',
]

// ── Helpers ───────────────────────────────────────────────────────────────

function suggestKwPrincipal(keywords: SeoPlanKeyword[]): SeoPlanKeyword | null {
  const hasGeo = (kw: string) =>
    GEO_TERMS.some(t => kw.toLowerCase().includes(t))
  const geoKws = keywords
    .filter(k => hasGeo(k.keyword))
    .sort((a, b) => (b.avg_monthly_searches ?? 0) - (a.avg_monthly_searches ?? 0))
  if (geoKws.length > 0) return geoKws[0]
  return [...keywords].sort(
    (a, b) => (b.avg_monthly_searches ?? 0) - (a.avg_monthly_searches ?? 0)
  )[0] ?? null
}

function fmtVolume(v: number | null): string {
  if (v == null) return '?'
  return v.toLocaleString('pt-BR')
}

function truncateUrl(url: string, max = 32): string {
  const stripped = url.replace(/^https?:\/\//, '')
  return stripped.length > max ? stripped.slice(0, max) + '…' : stripped
}

// ── Hook de debounce ─────────────────────────────────────────────────────

function useDebounce<Args extends unknown[]>(fn: (...args: Args) => void, ms: number) {
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)
  return useCallback(
    (...args: Args) => {
      clearTimeout(timer.current)
      timer.current = setTimeout(() => fn(...args), ms)
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [fn, ms]
  )
}

// ── Linha da tabela ───────────────────────────────────────────────────────

interface RowProps {
  page: SeoPlanPage
  projetoId: string
  savedRowId: number | null
  onSaved: (pageId: number) => void
}

function RegionRow({ reg }: { reg: RegionIntel }) {
  const scoreColor =
    reg.competitive_score >= 67 ? 'text-red-400' :
    reg.competitive_score >= 34 ? 'text-amber-400' : 'text-emerald-400'
  const DIFFICULTY_CHIP: Record<string, string> = {
    muito_baixa: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
    baixa:       'bg-green-500/10 text-green-400 border-green-500/30',
    media:       'bg-amber-500/10 text-amber-400 border-amber-500/30',
    alta:        'bg-orange-500/10 text-orange-400 border-orange-500/30',
    muito_alta:  'bg-red-500/10 text-red-400 border-red-500/30',
    // compatibilidade com dados antigos (on-page only)
    baixo:       'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
    medio:       'bg-amber-500/10 text-amber-400 border-amber-500/30',
    médio:       'bg-amber-500/10 text-amber-400 border-amber-500/30',
    alto:        'bg-red-500/10 text-red-400 border-red-500/30',
  }
  const chipColor = DIFFICULTY_CHIP[reg.difficulty_label] ?? 'bg-gray-500/10 text-gray-400 border-gray-500/30'

  const competitors = reg.competitors ?? (reg.top_competitor_url ? [{ url: reg.top_competitor_url, score: reg.competitive_score }] : [])

  return (
    <tr className="border-b border-gray-800/20 bg-gray-950/60">
      <td className="pl-8 pr-2 py-2 align-top">
        <span className="text-[10px] font-mono text-gray-600">{reg.geo_nome}</span>
      </td>
      <td />
      <td className="px-4 py-2 align-top">
        <span className="text-[10px] font-mono text-gray-600 italic">{reg.query}</span>
      </td>
      <td className="px-4 py-2 text-center align-top">
        <span className={`text-[10px] font-mono font-semibold ${scoreColor}`}>{reg.competitive_score}</span>
      </td>
      <td className="px-4 py-2 text-center align-top">
        <span className={`inline-flex items-center px-1.5 py-0.5 rounded border text-[10px] font-mono ${chipColor}`}>
          {reg.difficulty_label}
        </span>
      </td>
      <td className="px-4 py-2 align-top">
        {competitors.length > 0 ? (
          <ol className="space-y-0.5 list-none m-0 p-0">
            {competitors.map((c, i) => {
              const cScoreColor = c.score >= 67 ? 'text-red-400' : c.score >= 34 ? 'text-amber-400' : 'text-emerald-400'
              return (
                <li key={c.url} className="flex items-center gap-1">
                  <span className="text-[9px] font-mono text-gray-700 w-3 flex-shrink-0">{i + 1}.</span>
                  <a
                    href={c.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[10px] font-mono text-gray-500 hover:text-gray-300 transition-colors truncate max-w-[180px] inline-block"
                    title={c.url}
                  >
                    {truncateUrl(c.url, 28)} ↗
                  </a>
                  <span className={`text-[9px] font-mono ${cScoreColor} flex-shrink-0`}>({c.score})</span>
                  {c.backlink_score != null && (
                    <span className="text-[9px] font-mono text-blue-400 flex-shrink-0">
                      bl:{c.backlink_score}
                    </span>
                  )}
                </li>
              )
            })}
          </ol>
        ) : (
          <span className="text-[10px] font-mono text-gray-700">—</span>
        )}
      </td>
      <td />
    </tr>
  )
}

function PlanRow({ page, projetoId, savedRowId, onSaved }: RowProps) {
  const queryClient = useQueryClient()
  const [expanded, setExpanded] = useState(false)

  const suggested = useMemo(
    () => suggestKwPrincipal(page.keywords),
    [page.keywords]
  )

  const isSaved = savedRowId === page.id
  const isIncomplete = page.kw_principal_id == null
  const regioes = page.intel_data?.regioes ?? []
  const hasRegioes = regioes.length > 0

  const saveMutation = useMutation({
    mutationFn: (data: { kw_principal_id?: number | null; papel?: string | null }) =>
      seoPlanApi.updatePage(projetoId, page.id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['seo-plan', String(projetoId)] })
      onSaved(page.id)
    },
  })

  const debouncedSaveKw = useDebounce((kwId: number | null) => {
    saveMutation.mutate({ kw_principal_id: kwId })
  }, 400)

  const handlePapelChange = (papel: string) => {
    saveMutation.mutate({ papel })
  }

  const handleKwChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const val = e.target.value
    const kwId = val === '' ? null : Number(val)
    debouncedSaveKw(kwId)
  }

  return (
    <>
    <tr
      className={`border-b border-gray-800/50 transition-colors duration-300 ${
        isSaved ? 'bg-emerald-500/5' : 'hover:bg-gray-800/30'
      }`}
    >
      {/* Pesquisa */}
      <td className="px-4 py-3">
        <div className="flex items-center gap-1.5">
          {hasRegioes && (
            <button
              onClick={() => setExpanded(e => !e)}
              className="text-[10px] text-gray-600 hover:text-gray-300 transition-colors w-3 flex-shrink-0"
              title={expanded ? 'Recolher regiões' : 'Ver análise por região'}
            >
              {expanded ? '▼' : '▶'}
            </button>
          )}
          <span className="text-xs font-mono text-gray-100">{page.pesquisa_nome}</span>
        </div>
      </td>

      {/* Papel */}
      <td className="px-4 py-3" style={{ width: '160px' }}>
        <select
          value={page.papel ?? ''}
          onChange={e => handlePapelChange(e.target.value)}
          className="bg-gray-800 border border-gray-700 text-gray-100 text-xs font-mono rounded px-2 py-1 focus:outline-none focus:border-gray-500"
        >
          <option value="">— papel —</option>
          <option value="principal">principal</option>
          <option value="servico">serviço</option>
        </select>
      </td>

      {/* kw_principal */}
      <td className="px-4 py-3">
        <select
          defaultValue={page.kw_principal_id != null ? String(page.kw_principal_id) : ''}
          onChange={handleKwChange}
          className={`w-full bg-gray-800 text-gray-100 text-xs font-mono rounded px-2 py-1.5 focus:outline-none focus:border-gray-500 border ${
            isIncomplete ? 'border-amber-500/40' : 'border-gray-700'
          }`}
        >
          <option value="">— selecionar keyword —</option>
          {page.keywords.map(kw => {
            const isSuggested = suggested?.id === kw.id
            return (
              <option key={kw.id} value={String(kw.id)}>
                {isSuggested ? '★ ' : ''}{kw.keyword} ({fmtVolume(kw.avg_monthly_searches)}/mês)
              </option>
            )
          })}
        </select>
      </td>

      {/* Score — Phase 15 */}
      <td className="px-4 py-3 text-center" style={{ width: '72px' }}>
        {page.intel_updated_at == null ? (
          <span className="inline-flex items-center px-2 py-1 rounded bg-gray-800 text-gray-600 border border-gray-700 text-[10px] font-mono">
            Aguardando
          </span>
        ) : (
          <span className={`text-xs font-mono font-semibold ${
            (page.competitive_score ?? 0) >= 67 ? 'text-red-400' :
            (page.competitive_score ?? 0) >= 34 ? 'text-amber-400' :
            'text-emerald-400'
          }`}>
            {page.competitive_score}
          </span>
        )}
      </td>

      {/* Dificuldade — Phase 15 */}
      <td className="px-4 py-3 text-center" style={{ width: '104px' }}>
        {page.difficulty_label == null ? null : (
          <span className={`inline-flex items-center px-2 py-1 rounded border text-[10px] font-mono ${
            page.difficulty_label === 'alto'
              ? 'bg-red-500/10 text-red-400 border-red-500/30'
              : page.difficulty_label === 'médio'
              ? 'bg-amber-500/10 text-amber-400 border-amber-500/30'
              : 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
          }`}>
            {page.difficulty_label}
          </span>
        )}
      </td>

      {/* Competitor — Phase 15 */}
      <td className="px-4 py-3">
        {page.top_competitor_url ? (
          <a
            href={page.top_competitor_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[10px] font-mono text-gray-400 hover:text-gray-200 transition-colors truncate max-w-[200px] inline-block"
            title={page.top_competitor_url}
          >
            {truncateUrl(page.top_competitor_url, 32)} ↗
          </a>
        ) : (
          <span className="text-[10px] font-mono text-gray-700">—</span>
        )}
      </td>

      {/* Status */}
      <td className="px-4 py-3" style={{ width: '140px' }}>
        <span className="inline-flex items-center bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 text-[10px] font-mono px-2 py-1 rounded">
          Gate 2 ✓
        </span>
      </td>
    </tr>
    {expanded && regioes.map(reg => (
      <RegionRow key={reg.geo_nome} reg={reg} />
    ))}
    </>
  )
}

// ── Componente principal ──────────────────────────────────────────────────

export function SeoPlan() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [savedRowId, setSavedRowId] = useState<number | null>(null)
  const [toast, setToast] = useState(false)

  const { data, isLoading, isError, error, refetch } = useQuery<SeoPlanType>({
    queryKey: ['seo-plan', id],
    queryFn: () => seoPlanApi.get(id!),
    retry: false,
    staleTime: 0,
    refetchOnWindowFocus: true,
  })

  const generateMutation = useMutation({
    mutationFn: () => seoPlanApi.generate(id!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['seo-plan', id] })
    },
  })

  const readyMutation = useMutation({
    mutationFn: () => seoPlanApi.markReady(id!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['seo-plan', id] })
      setToast(true)
      setTimeout(() => setToast(false), 5000)
    },
  })

  const handleSaved = useCallback((pageId: number) => {
    setSavedRowId(pageId)
    setTimeout(() => setSavedRowId(prev => (prev === pageId ? null : prev)), 2000)
  }, [])

  // Geo targets state (Phase 15)
  const [showGeoForm, setShowGeoForm] = useState(false)
  const [newGeoNome, setNewGeoNome] = useState('')
  const [newGeoTipo, setNewGeoTipo] = useState<'bairro' | 'cidade' | 'estado'>('bairro')
  const [newGeoVol, setNewGeoVol] = useState<string>('')
  const [geoFormError, setGeoFormError] = useState<string | null>(null)

  const projetoIdNum = id!

  const { data: geoTargets = [], refetch: refetchGeos } = useQuery<GeoTarget[]>({
    queryKey: ['geo-targets', String(projetoIdNum)],
    queryFn: () => geoTargetsApi.list(projetoIdNum),
    enabled: !!projetoIdNum,
  })

  const addGeoMutation = useMutation({
    mutationFn: (data: GeoTargetCreate) => geoTargetsApi.create(projetoIdNum, data),
    onSuccess: () => {
      refetchGeos()
      setShowGeoForm(false)
      setNewGeoNome('')
      setNewGeoTipo('bairro')
      setNewGeoVol('')
      setGeoFormError(null)
    },
    onError: () => setGeoFormError('Erro ao adicionar. Tente novamente.'),
  })

  const deleteGeoMutation = useMutation({
    mutationFn: (geoId: number) => geoTargetsApi.delete(projetoIdNum, geoId),
    onSuccess: () => refetchGeos(),
  })

  // Loading
  if (isLoading) {
    return (
      <div className="min-h-full bg-gray-950 flex items-center justify-center">
        <p className="text-gray-500 font-mono text-sm">Carregando plano SEO...</p>
      </div>
    )
  }

  // Sem plano gerado ainda (404) ou erro de servidor
  if (isError && !data) {
    const is404 = (error as { response?: { status?: number } })?.response?.status === 404
    return (
      <div className="min-h-full bg-gray-950 flex items-center justify-center">
        <div className="text-center space-y-3">
          {is404 ? (
            <>
              <p className="text-gray-400 font-mono text-sm">Plano SEO ainda não gerado.</p>
              <p className="text-gray-600 font-mono text-xs">
                Acione o agente no Claude Code CLI:
              </p>
              <code className="block bg-gray-900 border border-gray-800 rounded-lg px-4 py-2 text-emerald-400 font-mono text-sm">
                /seo-architect {id}
              </code>
            </>
          ) : (
            <p className="text-red-400 font-mono text-sm">Erro ao carregar plano SEO. Tente recarregar a página.</p>
          )}
        </div>
      </div>
    )
  }

  const allReady = (data?.pages ?? []).length > 0 &&
    (data?.pages ?? []).every(p => p.kw_principal_id != null)

  const isPronto = data?.status === 'pronto'
  const isPending = data?.competitive_intel_pending ?? false
  const hasSemPlano = (data?.pesquisas_sem_plano ?? []).length > 0

  return (
    <div className="min-h-full bg-gray-950">
      {/* Header sticky */}
      <div className="sticky top-0 z-10 border-b border-gray-800 bg-gray-900/50 backdrop-blur-sm">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button
              onClick={() => navigate(`/projetos/${id}`)}
              className="text-gray-600 hover:text-gray-400 font-mono text-xs transition-colors"
            >
              ← projeto
            </button>
            <div>
              <h1 className="font-mono text-sm font-semibold text-gray-100">Plano SEO</h1>
              {data && (
                <span className={`text-[10px] font-mono ${data.status === 'pronto' ? 'text-emerald-400' : 'text-gray-600'}`}>
                  {data.status === 'pronto' ? 'pronto' : 'rascunho'}
                </span>
              )}
            </div>
          </div>

          {/* Ações à direita */}
          <div className="flex items-center gap-2">
            <button
              onClick={() => refetch()}
              className="px-2 py-1 text-[10px] font-mono text-gray-600 hover:text-gray-400 border border-gray-800 hover:border-gray-700 rounded transition-colors"
              title="Atualizar dados"
            >
              ↻
            </button>
            {data && (
              <>
                {isPending ? (
                  <button
                    disabled
                    className="px-3 py-2 text-xs font-mono bg-amber-500/10 text-amber-400 border border-amber-500/25 rounded-lg cursor-not-allowed"
                  >
                    Aguardando Competitive Intel
                  </button>
                ) : isPronto ? (
                  <span className="px-3 py-2 text-xs font-mono text-emerald-400 border border-emerald-500/30 rounded-lg bg-emerald-500/10">
                    Intel Concluído ✓
                  </span>
                ) : (
                  <button
                    onClick={() => readyMutation.mutate()}
                    disabled={!allReady || readyMutation.isPending}
                    title={!allReady ? 'Eleja kw_principal em todas as pesquisas para continuar' : undefined}
                    className={`px-3 py-2 text-xs font-mono rounded-lg transition-colors ${
                      allReady && !readyMutation.isPending
                        ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/20'
                        : 'bg-gray-800 text-gray-600 border border-gray-700 cursor-not-allowed opacity-50'
                    }`}
                  >
                    Marcar como Pronto
                  </button>
                )}
              </>
            )}
          </div>
        </div>
      </div>

      {/* Painel Regiões Alvo (Phase 15) */}
      {data && (
        <div className="border-b border-gray-800 bg-gray-900/50 px-6 py-4">
          <div className="max-w-7xl mx-auto flex items-center flex-wrap gap-2">
            <span className="text-[10px] font-mono uppercase tracking-wider text-gray-600 mr-4">
              REGIÕES ALVO
            </span>

            {geoTargets.map(geo => (
              <span
                key={geo.id}
                className={`inline-flex items-center gap-1 px-2 py-1 bg-gray-800 border border-gray-700 text-xs font-mono text-gray-300 rounded ${deleteGeoMutation.isPending ? 'opacity-50 pointer-events-none' : ''}`}
                title={geo.volume_estimado ? `${geo.volume_estimado.toLocaleString('pt-BR')}/mês` : undefined}
              >
                {geo.nome.length > 24 ? geo.nome.slice(0, 24) + '…' : geo.nome}
                <button
                  onClick={() => deleteGeoMutation.mutate(geo.id)}
                  className="text-[10px] text-gray-600 hover:text-red-400 transition-colors ml-1 cursor-pointer"
                >×</button>
              </span>
            ))}

            {!showGeoForm && (
              <button
                onClick={() => setShowGeoForm(true)}
                className="inline-flex items-center gap-1 px-2 py-1 bg-gray-800/50 border border-dashed border-gray-700/50 text-xs font-mono text-gray-600 hover:text-gray-400 hover:border-gray-600 rounded cursor-pointer transition-colors"
              >
                + Adicionar região
              </button>
            )}

            {showGeoForm && (
              <div className="flex items-center gap-2 flex-wrap">
                <input
                  value={newGeoNome}
                  onChange={e => setNewGeoNome(e.target.value)}
                  placeholder="nome do bairro"
                  maxLength={100}
                  className="bg-gray-800 border border-gray-700 text-gray-100 text-xs font-mono rounded px-2 py-1 focus:outline-none focus:border-gray-500 w-36"
                />
                <select
                  value={newGeoTipo}
                  onChange={e => setNewGeoTipo(e.target.value as 'bairro' | 'cidade' | 'estado')}
                  className="bg-gray-800 border border-gray-700 text-gray-100 text-xs font-mono rounded px-2 py-1 focus:outline-none focus:border-gray-500 w-28"
                >
                  <option value="">— tipo —</option>
                  <option value="bairro">bairro</option>
                  <option value="cidade">cidade</option>
                  <option value="estado">estado</option>
                </select>
                <input
                  value={newGeoVol}
                  onChange={e => setNewGeoVol(e.target.value)}
                  placeholder="vol/mês (opcional)"
                  type="number"
                  min="0"
                  className="bg-gray-800 border border-gray-700 text-gray-100 text-xs font-mono rounded px-2 py-1 focus:outline-none focus:border-gray-500 w-36"
                />
                <button
                  onClick={() => addGeoMutation.mutate({
                    nome: newGeoNome.trim(),
                    tipo: newGeoTipo || undefined,
                    volume_estimado: newGeoVol ? parseInt(newGeoVol, 10) : null,
                  })}
                  disabled={!newGeoNome.trim() || addGeoMutation.isPending}
                  className="px-3 py-1 text-xs font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 rounded hover:bg-emerald-500/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Adicionar
                </button>
                <button
                  onClick={() => { setShowGeoForm(false); setGeoFormError(null) }}
                  className="px-3 py-1 text-xs font-mono text-gray-600 hover:text-gray-400 transition-colors"
                >
                  cancelar
                </button>
                {geoFormError && (
                  <span className="text-[10px] font-mono text-red-400 w-full">{geoFormError}</span>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Conteúdo principal */}
      <div className="max-w-7xl mx-auto px-6 py-6">

        {/* Estado vazio — sem plano */}
        {!data && (
          <div className="py-16 flex flex-col items-center gap-4 text-center">
            <p className="font-mono text-sm text-gray-500">Nenhuma pesquisa aprovada no Gate 2 ainda.</p>
            <p className="font-mono text-xs text-gray-600">Aprove pelo menos uma pesquisa no Gate 2 para gerar o plano SEO.</p>
            <button
              disabled
              className="px-3 py-2 text-xs font-mono bg-gray-800 text-gray-600 border border-gray-700 rounded-lg cursor-not-allowed opacity-50"
            >
              Gerar Plano
            </button>
          </div>
        )}

        {/* Plano existe */}
        {data && (
          <>
            {/* Banner de regeneração */}
            {hasSemPlano && (
              <div className="mb-4 bg-amber-500/10 border border-amber-500/25 rounded-lg px-4 py-3 flex items-center justify-between">
                <span className="text-xs font-mono text-amber-400">
                  {data.pesquisas_sem_plano.length} pesquisa(s) aprovadas no Gate 2 não estão no plano.
                </span>
                <button
                  onClick={() => generateMutation.mutate()}
                  disabled={generateMutation.isPending}
                  className="px-3 py-2 text-xs font-mono bg-amber-500/10 text-amber-400 border border-amber-500/25 rounded-lg hover:bg-amber-500/20 transition-colors disabled:opacity-50"
                >
                  Regenerar Plano
                </button>
              </div>
            )}

            {/* Tabela */}
            {data.pages.length === 0 ? (
              <div className="py-16 flex flex-col items-center gap-4 text-center">
                <p className="font-mono text-sm text-gray-500">Nenhuma pesquisa aprovada no Gate 2 ainda.</p>
                <p className="font-mono text-xs text-gray-600">Aprove pelo menos uma pesquisa no Gate 2 para gerar o plano SEO.</p>
                <button
                  onClick={() => generateMutation.mutate()}
                  disabled={generateMutation.isPending}
                  className="px-4 py-2 text-sm font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 rounded-lg hover:bg-emerald-500/20 transition-colors disabled:opacity-50"
                >
                  Gerar Plano
                </button>
              </div>
            ) : (
              <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
                <table className="w-full text-sm font-mono">
                  <thead>
                    <tr className="border-b border-gray-800">
                      <th className="px-4 py-3 text-[10px] uppercase tracking-wider text-gray-600 font-mono text-left">Pesquisa</th>
                      <th className="px-4 py-3 text-[10px] uppercase tracking-wider text-gray-600 font-mono text-left" style={{ width: '160px' }}>Papel</th>
                      <th className="px-4 py-3 text-[10px] uppercase tracking-wider text-gray-600 font-mono text-left">KW Principal</th>
                      <th className="px-4 py-3 text-[10px] uppercase tracking-wider text-gray-600 font-mono text-center" style={{ width: '72px' }}>Score</th>
                      <th className="px-4 py-3 text-[10px] uppercase tracking-wider text-gray-600 font-mono text-center" style={{ width: '104px' }}>Dificuldade</th>
                      <th className="px-4 py-3 text-[10px] uppercase tracking-wider text-gray-600 font-mono text-left">Competitor</th>
                      <th className="px-4 py-3 text-[10px] uppercase tracking-wider text-gray-600 font-mono text-left" style={{ width: '140px' }}>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.pages.map(page => (
                      <PlanRow
                        key={page.id}
                        page={page}
                        projetoId={id!}
                        savedRowId={savedRowId}
                        onSaved={handleSaved}
                      />
                    ))}
                  </tbody>
                </table>

                {/* Footer informativo */}
                <div className="px-4 py-3 border-t border-gray-800">
                  <p className="font-mono text-[10px] text-gray-700">
                    Selecione a keyword principal de cada pesquisa para habilitar o botão Marcar como Pronto.
                  </p>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* Toast de confirmação */}
      {toast && (
        <div className="fixed bottom-6 right-6 z-50 font-mono text-xs bg-emerald-900/90 text-emerald-200 border border-emerald-500/40 px-4 py-2 rounded-lg shadow-lg">
          Plano marcado como pronto — Competitive Intel enfileirado.
        </div>
      )}
    </div>
  )
}
