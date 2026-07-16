import { useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { projetosApi, pesquisasApi, pipelineApi, type ProjetoDetail, type Projeto, type ProjetoStatus, type ProjetoMetadata, type Pesquisa, type AgentExecution } from '../lib/api'

// ── Config objetos ────────────────────────────────────────────────────────────

const TIPO_CFG = {
  rank_rent:         { label: 'Rank & Rent', cls: 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30' },
  infoproduto:       { label: 'Infoproduto',  cls: 'bg-violet-500/10 text-violet-400 border border-violet-500/30' },
  youtube_faceless:  { label: 'YouTube',      cls: 'bg-red-500/10 text-red-400 border border-red-500/30' },
  facebook_faceless: { label: 'Facebook',     cls: 'bg-blue-500/10 text-blue-400 border border-blue-500/30' },
  prospeccao:        { label: 'Prospecção',   cls: 'bg-amber-500/10 text-amber-400 border border-amber-500/30' },
} as const

const STATUS_CFG: Record<string, { label: string; cls: string }> = {
  rascunho:  { label: 'Rascunho',         cls: 'bg-gray-800 text-gray-500 border border-gray-700' },
  ativo:     { label: 'Ativo',            cls: 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/25' },
  pausado:   { label: 'Pausado',          cls: 'bg-amber-500/10 text-amber-400 border border-amber-500/25' },
  encerrado: { label: 'Encerrado',        cls: 'bg-gray-800/50 text-gray-600 border border-gray-800' },
  research:  { label: 'Keyword Research', cls: 'bg-blue-500/10 text-blue-400 border border-blue-500/25' },
  gate1:     { label: 'Aprovado',         cls: 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/25' },
  gate2:     { label: 'Intel + SEO',      cls: 'bg-violet-500/10 text-violet-400 border border-violet-500/25' },
  publicado: { label: 'Publicado',        cls: 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/40' },
}

// Status válidos por tipo — reflete pipeline atual (sem Gates separados)
const STATUS_POR_TIPO: Record<string, ProjetoStatus[]> = {
  rank_rent:         ['rascunho', 'research', 'gate1', 'gate2', 'publicado', 'pausado', 'encerrado'],
  infoproduto:       ['rascunho', 'ativo', 'pausado', 'encerrado'],
  youtube_faceless:  ['rascunho', 'ativo', 'pausado', 'encerrado'],
  facebook_faceless: ['rascunho', 'ativo', 'pausado', 'encerrado'],
  prospeccao:        ['rascunho', 'ativo', 'pausado', 'encerrado'],
}

// ── Inline components ─────────────────────────────────────────────────────────

function Spinner({ size = 'sm' }: { size?: 'sm' | 'md' }) {
  const cls = size === 'sm' ? 'w-3.5 h-3.5' : 'w-5 h-5'
  return (
    <span className={`inline-block ${cls} border border-current border-t-transparent rounded-full animate-spin opacity-60`} />
  )
}

// ── Metadata section ──────────────────────────────────────────────────────────

type MetaKey = keyof ProjetoMetadata

type MetaFieldDef = { label: string; key: MetaKey }

function getMetaFields(tipo: Projeto['tipo']): MetaFieldDef[] {
  switch (tipo) {
    case 'rank_rent':         return [{ label: 'Nicho', key: 'nicho' }, { label: 'Cidade', key: 'cidade' }, { label: 'URL do site', key: 'site_url' }]
    case 'infoproduto':       return [{ label: 'Produto', key: 'produto' }, { label: 'Plataforma', key: 'plataforma' }, { label: 'Nicho', key: 'nicho' }]
    case 'youtube_faceless':  return [{ label: 'Canal', key: 'canal' }, { label: 'Nicho', key: 'nicho' }, { label: 'Idioma', key: 'idioma' }]
    case 'facebook_faceless': return [{ label: 'Página', key: 'pagina' }, { label: 'Nicho', key: 'nicho' }, { label: 'Formato', key: 'formato' }]
    case 'prospeccao':        return [{ label: 'Nicho', key: 'nicho' }, { label: 'Cidade', key: 'cidade' }]
  }
}

function MetadataSection({
  projeto,
  onSave,
}: {
  projeto: Projeto
  onSave: (patch: Partial<Omit<Projeto, 'id' | 'created_at'>>) => Promise<void>
}) {
  const [editingKey, setEditingKey] = useState<MetaKey | null>(null)
  const [localValue, setLocalValue] = useState('')

  const fields = getMetaFields(projeto.tipo)

  const startEdit = useCallback((key: MetaKey, current: string | undefined) => {
    setLocalValue(current ?? '')
    setEditingKey(key)
  }, [])

  const commitEdit = useCallback(async () => {
    if (!editingKey) return
    setEditingKey(null)
    const current = projeto.metadata[editingKey]
    if (localValue === (current ?? '')) return
    await onSave({ metadata: { ...projeto.metadata, [editingKey]: localValue || undefined } })
  }, [editingKey, localValue, projeto.metadata, onSave])

  return (
    <div className="grid grid-cols-2 gap-4">
      {fields.map(f => (
        <div key={f.key}>
          <p className="text-[10px] font-mono text-gray-600 uppercase tracking-wider mb-0.5">{f.label}</p>
          {editingKey === f.key ? (
            <input
              autoFocus
              value={localValue}
              onChange={e => setLocalValue(e.target.value)}
              onBlur={commitEdit}
              onKeyDown={e => { if (e.key === 'Enter') commitEdit() }}
              className="bg-transparent font-mono text-sm text-gray-100 border-b border-emerald-400 focus:outline-none w-full"
            />
          ) : (
            <p
              onClick={() => startEdit(f.key, projeto.metadata[f.key])}
              className={`text-sm font-mono cursor-text hover:text-white ${projeto.metadata[f.key] ? 'text-gray-300' : 'text-gray-700 italic'}`}
            >
              {projeto.metadata[f.key] || '— clique para editar'}
            </p>
          )}
        </div>
      ))}
    </div>
  )
}

// ── Config pesquisa status ────────────────────────────────────────────────────

const PESQUISA_STATUS_CFG: Record<string, { label: string; cls: string }> = {
  pending_review: { label: 'Pesquisando',        cls: 'bg-gray-800 text-gray-500 border border-gray-700' },
  approved:       { label: 'Classificando',      cls: 'bg-amber-500/10 text-amber-400 border border-amber-500/25' },
  rejected:       { label: 'Rejeitada',          cls: 'bg-red-500/10 text-red-400 border border-red-500/25' },
  classificado:   { label: 'Aguardando revisão', cls: 'bg-violet-500/10 text-violet-400 border border-violet-500/25' },
  aprovado:       { label: 'Aprovada',           cls: 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30' },
}

const PAPEL_CFG = {
  principal: { label: 'Principal', cls: 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30' },
  servico:   { label: 'Serviço',   cls: 'bg-violet-500/10 text-violet-400 border border-violet-500/30' },
} as const

// ── VincularPesquisaModal ─────────────────────────────────────────────────────

function VincularPesquisaModal({
  projetoId,
  pesquisasJaVinculadas,
  onClose,
  onVinculada,
  pesquisaEditando,
}: {
  projetoId: string
  pesquisasJaVinculadas: string[]
  onClose: () => void
  onVinculada: () => void
  pesquisaEditando?: Pesquisa
}) {
  const editMode = !!pesquisaEditando
  const [selectedId, setSelectedId] = useState<string>(pesquisaEditando?.id ?? '')
  const [papel, setPapel] = useState<'principal' | 'servico'>(pesquisaEditando?.papel ?? 'principal')
  const [servico_slug, setServico_slug] = useState(pesquisaEditando?.servico_slug ?? '')
  const [submitting, setSubmitting] = useState(false)
  const [erro, setErro] = useState('')

  const { data: todasPesquisas, isLoading } = useQuery({
    queryKey: ['pesquisas-todas'],
    queryFn: () => pesquisasApi.list(),
    enabled: !editMode,
  })

  const disponiveis = (todasPesquisas ?? []).filter(
    (p: Pesquisa) => !pesquisasJaVinculadas.includes(p.id)
  )

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!selectedId) return
    setSubmitting(true)
    setErro('')
    try {
      await pesquisasApi.vincular(selectedId, {
        projeto_id: projetoId,
        papel,
        servico_slug: papel === 'servico' && servico_slug ? servico_slug : undefined,
      })
      onVinculada()
      onClose()
    } catch {
      setErro(editMode ? 'Erro ao salvar alterações. Tente novamente.' : 'Erro ao vincular pesquisa. Tente novamente.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-40 bg-black/70 backdrop-blur-sm flex items-center justify-center">
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-8 max-w-lg w-full mx-4 relative">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-gray-600 hover:text-gray-300 font-mono text-sm"
        >
          ×
        </button>
        <h2 className="font-mono font-semibold text-gray-100 mb-1">
          {editMode ? 'Editar vínculo' : 'Vincular pesquisa'}
        </h2>
        <p className="text-xs font-mono text-gray-600 mb-6">
          {editMode
            ? `Editando papel e slug de "${pesquisaEditando?.projeto_nome || pesquisaEditando?.nicho}"`
            : 'Selecione uma pesquisa existente e defina o papel'}
        </p>

        {isLoading && (
          <div className="flex items-center gap-2 text-gray-600 text-sm font-mono mb-4">
            <Spinner /> Carregando pesquisas...
          </div>
        )}

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          {/* Seleção da pesquisa — apenas no modo vincular */}
          {!editMode && (
            <div>
              <label className="text-xs font-mono text-gray-500 mb-1.5 block">Pesquisa</label>
              <select
                value={selectedId}
                onChange={e => setSelectedId(e.target.value)}
                required
                className="bg-gray-950 border border-gray-800 rounded-lg px-3 py-2.5 text-sm font-mono text-gray-100 focus:outline-none focus:border-gray-600 w-full cursor-pointer"
              >
                <option value="" className="bg-gray-900">— selecionar —</option>
                {disponiveis.map((p: Pesquisa) => (
                  <option key={p.id} value={p.id} className="bg-gray-900">
                    {p.projeto_nome || p.nicho} · {p.cidade} ({p.status})
                  </option>
                ))}
              </select>
              {!isLoading && disponiveis.length === 0 && (
                <p className="text-xs font-mono text-gray-600 mt-1">Nenhuma pesquisa disponível para vincular.</p>
              )}
            </div>
          )}

          {/* Papel */}
          <div>
            <label className="text-xs font-mono text-gray-500 mb-1.5 block">Papel</label>
            <select
              value={papel}
              onChange={e => setPapel(e.target.value as 'principal' | 'servico')}
              className="bg-gray-950 border border-gray-800 rounded-lg px-3 py-2.5 text-sm font-mono text-gray-100 focus:outline-none focus:border-gray-600 w-full cursor-pointer"
            >
              <option value="principal" className="bg-gray-900">Principal (home: /)</option>
              <option value="servico" className="bg-gray-900">Serviço (/servicos/{'{slug}'})</option>
            </select>
          </div>

          {/* Slug (somente quando papel = servico) */}
          {papel === 'servico' && (
            <div>
              <label className="text-xs font-mono text-gray-500 mb-1.5 block">Slug do serviço</label>
              <input
                type="text"
                value={servico_slug}
                onChange={e => setServico_slug(e.target.value)}
                placeholder="ex: encanamento, eletricista"
                className="bg-gray-950 border border-gray-800 rounded-lg px-3 py-2.5 text-sm font-mono text-gray-100 placeholder-gray-700 focus:outline-none focus:border-gray-600 w-full"
              />
            </div>
          )}

          {erro && (
            <p className="text-xs font-mono text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
              {erro}
            </p>
          )}

          <div className="flex items-center justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              className="px-4 py-2 text-sm font-mono text-gray-500 border border-gray-800 rounded-lg hover:text-gray-300 hover:border-gray-700 disabled:opacity-30"
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={submitting || !selectedId}
              className="px-4 py-2 text-sm font-mono bg-emerald-600 text-white rounded-lg hover:bg-emerald-500 disabled:opacity-30 flex items-center gap-2"
            >
              {submitting ? <><Spinner /> {editMode ? 'Salvando...' : 'Vinculando...'}</> : editMode ? 'Salvar →' : 'Vincular →'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── PesquisasSection ──────────────────────────────────────────────────────────

function PesquisasSection({
  projeto,
  onVinculada,
}: {
  projeto: ProjetoDetail
  onVinculada: () => void
}) {
  const queryClient = useQueryClient()
  const [showModal, setShowModal] = useState(false)
  const [editingPesquisa, setEditingPesquisa] = useState<Pesquisa | null>(null)
  const [desvinculando, setDesvinculando] = useState<string | null>(null)

  const pesquisasJaVinculadas = projeto.pesquisas.map((p: Pesquisa) => p.id)

  async function handleDesvincular(p: Pesquisa) {
    if (!confirm(`Desvincular "${p.projeto_nome || p.nicho}" deste projeto?`)) return
    setDesvinculando(p.id)
    try {
      await pesquisasApi.desvincular(p.id)
      queryClient.invalidateQueries({ queryKey: ['projeto', String(projeto.id)] })
    } catch {
      // silent
    } finally {
      setDesvinculando(null)
    }
  }

  function handleVinculadaOuEditada() {
    queryClient.invalidateQueries({ queryKey: ['projeto', String(projeto.id)] })
    onVinculada()
  }

  return (
    <>
      <section className="bg-gray-900 border border-gray-800 rounded-lg p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xs font-mono font-semibold uppercase tracking-wider text-gray-600">
            Planos de Palavras-chave
          </h2>
          <button
            onClick={() => setShowModal(true)}
            className="text-xs font-mono text-emerald-400 border border-emerald-500/30 px-3 py-1 rounded-lg hover:bg-emerald-500/10 transition-colors"
          >
            + Vincular pesquisa existente
          </button>
        </div>

        {projeto.pesquisas.length === 0 ? (
          <p className="text-sm font-mono text-gray-700 italic">Nenhuma pesquisa vinculada ainda.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm font-mono">
              <thead>
                <tr className="text-[10px] text-gray-600 uppercase tracking-wider border-b border-gray-800">
                  <th className="text-left pb-2 pr-4">Pesquisa</th>
                  <th className="text-left pb-2 pr-4">Papel</th>
                  <th className="text-left pb-2 pr-4">Status</th>
                  <th className="text-left pb-2 pr-4">Slug</th>
                  <th className="pb-2" />
                </tr>
              </thead>
              <tbody>
                {projeto.pesquisas.map((p: Pesquisa) => {
                  const statusCfg = PESQUISA_STATUS_CFG[p.status] ?? { label: p.status, cls: 'bg-gray-800 text-gray-500 border border-gray-700' }
                  const papelCfg = p.papel ? PAPEL_CFG[p.papel] : null
                  return (
                    <tr key={p.id} className="border-b border-gray-800/50 last:border-0 hover:bg-gray-800/30 transition-colors group">
                      <td className="py-3 pr-4">
                        <span className="text-gray-200">{p.projeto_nome || p.nicho}</span>
                        {p.cidade && <span className="text-gray-600 ml-2 text-xs">{p.cidade}</span>}
                      </td>
                      <td className="py-3 pr-4">
                        {papelCfg ? (
                          <span className={`text-xs px-2 py-0.5 rounded-full border ${papelCfg.cls}`}>
                            {papelCfg.label}
                          </span>
                        ) : (
                          <span className="text-gray-700 text-xs italic">—</span>
                        )}
                      </td>
                      <td className="py-3 pr-4">
                        <span className={`text-xs px-2 py-0.5 rounded-full border ${statusCfg.cls}`}>
                          {statusCfg.label}
                        </span>
                      </td>
                      <td className="py-3 pr-4 text-gray-500 text-xs">
                        {p.servico_slug ? (
                          <span className="text-gray-400">/servicos/{p.servico_slug}</span>
                        ) : p.papel === 'principal' ? (
                          <span className="text-gray-600">/</span>
                        ) : (
                          <span className="text-gray-700">—</span>
                        )}
                      </td>
                      <td className="py-3 text-right">
                        <div className="flex items-center justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button
                            onClick={() => setEditingPesquisa(p)}
                            className="text-[11px] font-mono text-gray-500 hover:text-gray-200 px-2 py-0.5 rounded border border-transparent hover:border-gray-700 transition-colors"
                          >
                            editar
                          </button>
                          <button
                            onClick={() => handleDesvincular(p)}
                            disabled={desvinculando === p.id}
                            className="text-[11px] font-mono text-red-600 hover:text-red-400 px-2 py-0.5 rounded border border-transparent hover:border-red-500/30 disabled:opacity-40 transition-colors"
                          >
                            {desvinculando === p.id ? <Spinner /> : 'desvincular'}
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {showModal && (
        <VincularPesquisaModal
          projetoId={projeto.id}
          pesquisasJaVinculadas={pesquisasJaVinculadas}
          onClose={() => setShowModal(false)}
          onVinculada={() => { handleVinculadaOuEditada(); setShowModal(false) }}
        />
      )}

      {editingPesquisa && (
        <VincularPesquisaModal
          projetoId={projeto.id}
          pesquisasJaVinculadas={pesquisasJaVinculadas}
          pesquisaEditando={editingPesquisa}
          onClose={() => setEditingPesquisa(null)}
          onVinculada={() => { handleVinculadaOuEditada(); setEditingPesquisa(null) }}
        />
      )}
    </>
  )
}

// ── HistoricoSection ──────────────────────────────────────────────────────────

const AGENT_LABEL: Record<string, string> = {
  kw_validator:    'Keyword Validator',
  kw_research:     'Keyword Research',
  competitive_intel: 'Competitive Intel',
  seo_architect:   'SEO Architect',
  content_writer:  'Content Writer',
  content_reviewer:'Content Reviewer',
  site_builder:    'Site Builder',
  seo_auditor:     'SEO Auditor',
  rank_intel:      'Rank Intel',
}

const EXEC_STATUS_CFG: Record<string, { label: string; dot: string; cls: string }> = {
  pending:     { label: 'Pendente',    dot: 'bg-gray-500',    cls: 'text-gray-500' },
  in_progress: { label: 'Executando', dot: 'bg-amber-400 animate-pulse', cls: 'text-amber-400' },
  completed:   { label: 'Concluído',  dot: 'bg-emerald-400', cls: 'text-emerald-400' },
  failed:      { label: 'Falhou',     dot: 'bg-red-400',     cls: 'text-red-400' },
}

function HistoricoSection({ projetoId }: { projetoId: string }) {
  const { data: executions = [], isLoading } = useQuery<AgentExecution[]>({
    queryKey: ['pipeline', String(projetoId)],
    queryFn: () => pipelineApi.get(projetoId),
    refetchInterval: 30_000,
  })

  const sorted = [...executions].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  )

  function fmtDate(iso: string | null | undefined) {
    if (!iso) return '—'
    const d = new Date(iso)
    return d.toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' }) +
      ' · ' + d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
  }

  return (
    <section className="bg-gray-900 border border-gray-800 rounded-lg p-5">
      <h2 className="text-xs font-mono font-semibold uppercase tracking-wider text-gray-600 mb-4">
        Histórico
      </h2>

      {isLoading ? (
        <div className="flex items-center gap-2 text-gray-600 text-xs font-mono">
          <Spinner /> Carregando...
        </div>
      ) : sorted.length === 0 ? (
        <p className="text-xs font-mono text-gray-700 italic">
          Nenhum agente executado ainda.
        </p>
      ) : (
        <div className="space-y-0">
          {sorted.map((exec, i) => {
            const cfg = EXEC_STATUS_CFG[exec.status] ?? EXEC_STATUS_CFG.pending
            const label = AGENT_LABEL[exec.agent_name] ?? exec.agent_name
            const isLast = i === sorted.length - 1
            return (
              <div key={exec.id} className="flex items-start gap-3 relative">
                {/* linha vertical conectando entradas */}
                {!isLast && (
                  <div className="absolute left-[5px] top-4 bottom-0 w-px bg-gray-800" />
                )}
                <div className={`mt-1.5 w-2.5 h-2.5 rounded-full flex-shrink-0 ${cfg.dot}`} />
                <div className="flex-1 pb-4">
                  <div className="flex items-center justify-between gap-4">
                    <span className="font-mono text-sm text-gray-200">{label}</span>
                    <span className={`text-[10px] font-mono ${cfg.cls}`}>{cfg.label}</span>
                  </div>
                  <div className="flex items-center gap-3 mt-0.5">
                    <span className="text-[10px] font-mono text-gray-600">
                      {fmtDate(exec.started_at ?? exec.created_at)}
                    </span>
                    {exec.completed_at && (
                      <span className="text-[10px] font-mono text-gray-700">
                        → {fmtDate(exec.completed_at)}
                      </span>
                    )}
                  </div>
                  {exec.error_message && (
                    <p className="mt-1 text-[10px] font-mono text-red-400 bg-red-500/10 border border-red-500/20 rounded px-2 py-1">
                      {exec.error_message}
                    </p>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}

// ── Componente principal ──────────────────────────────────────────────────────

export function ProjetoDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  // Estado local para inline edit
  const [editingNome, setEditingNome] = useState(false)
  const [nomeLocal, setNomeLocal] = useState('')
  const [editingReceita, setEditingReceita] = useState(false)
  const [receitaLocal, setReceitaLocal] = useState('')
  const [deleting, setDeleting] = useState(false)

  const { data: projeto, isLoading, error } = useQuery({
    queryKey: ['projeto', id],
    queryFn: () => projetosApi.get(id!),
    enabled: !!id,
  })

  const { data: executions = [] } = useQuery<AgentExecution[]>({
    queryKey: ['pipeline', id],
    queryFn: () => pipelineApi.get(id!),
    enabled: !!id,
    refetchInterval: 30_000,
  })

  // Atualização otimista com rollback
  async function handleInlineUpdate(patch: Partial<Omit<Projeto, 'id' | 'created_at'>>) {
    if (!projeto) return
    const original = { ...projeto }
    // Otimista: invalida para refetch imediato
    try {
      await projetosApi.update(id!, patch)
      queryClient.invalidateQueries({ queryKey: ['projeto', id] })
      queryClient.invalidateQueries({ queryKey: ['projetos'] })
    } catch {
      // rollback — força refetch com dados originais
      queryClient.setQueryData(['projeto', id], original)
    }
  }

  async function handleNomeSave() {
    setEditingNome(false)
    if (!projeto || nomeLocal === projeto.projeto_nome) return
    await handleInlineUpdate({ projeto_nome: nomeLocal })
  }

  async function handleStatusChange(e: React.ChangeEvent<HTMLSelectElement>) {
    await handleInlineUpdate({ status: e.target.value as ProjetoStatus })
  }

  function handleReceitaEdit() {
    setReceitaLocal(projeto?.receita_mensal != null ? String(projeto.receita_mensal) : '')
    setEditingReceita(true)
  }

  async function handleReceitaSave() {
    setEditingReceita(false)
    const valor = receitaLocal === '' ? null : parseFloat(receitaLocal)
    if (!isNaN(valor ?? 0)) {
      await handleInlineUpdate({ receita_mensal: valor })
    }
  }

  function handleVincular() {
    queryClient.invalidateQueries({ queryKey: ['projeto', id] })
  }

  async function handleDelete() {
    if (!projeto) return
    if (!confirm(`Excluir o projeto "${projeto.projeto_nome}"? Esta ação não pode ser desfeita.`)) return
    setDeleting(true)
    try {
      await projetosApi.delete(id!)
      queryClient.invalidateQueries({ queryKey: ['projetos'] })
      navigate('/projetos')
    } catch {
      // silent
    } finally {
      setDeleting(false)
    }
  }

  if (isLoading) return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center">
      <div className="flex items-center gap-2.5 text-gray-600 text-sm font-mono">
        <Spinner size="md" /> Carregando projeto...
      </div>
    </div>
  )

  if (error || !projeto) return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center">
      <p className="text-red-400 text-sm font-mono">Erro ao carregar projeto. Tente recarregar a página.</p>
    </div>
  )

  const tipo = TIPO_CFG[projeto.tipo] ?? { label: projeto.tipo, cls: 'bg-gray-800 text-gray-500 border border-gray-700' }
  const statusCfg = STATUS_CFG[projeto.status] ?? { label: projeto.status, cls: 'bg-gray-800 text-gray-500 border border-gray-700' }
  const statusOpcoes = STATUS_POR_TIPO[projeto.tipo] ?? ['rascunho', 'ativo', 'pausado', 'encerrado']

  return (
    <div className="min-h-screen bg-gray-950">
      {/* Sticky header */}
      <header className="sticky top-0 z-10 bg-gray-950/95 backdrop-blur border-b border-gray-800 px-6 py-3.5">
        <div className="max-w-3xl mx-auto flex items-center gap-4">
          <button
            onClick={() => navigate('/projetos')}
            className="font-mono text-sm text-gray-600 hover:text-gray-300 transition-colors"
          >
            ← voltar
          </button>
          <div className="h-4 w-px bg-gray-800" />
          <div className="min-w-0 flex-1 flex items-center gap-2 flex-wrap">
            <span className="font-mono font-semibold text-gray-100 truncate">{projeto.projeto_nome}</span>
            <span className={`text-xs font-mono px-2 py-0.5 rounded-full whitespace-nowrap ${tipo.cls}`}>
              {tipo.label}
            </span>
            <span className={`text-xs font-mono px-2 py-0.5 rounded-full whitespace-nowrap ${statusCfg.cls}`}>
              {statusCfg.label}
            </span>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="max-w-3xl mx-auto px-6 py-8 space-y-6">

        {/* Bloco: Informações gerais */}
        <section className="bg-gray-900 border border-gray-800 rounded-lg p-5">
          <h2 className="text-xs font-mono font-semibold uppercase tracking-wider text-gray-600 mb-4">
            Informações gerais
          </h2>
          <div className="grid grid-cols-2 gap-4">

            {/* Nome — inline edit */}
            <div className="col-span-2">
              <p className="text-[10px] font-mono text-gray-600 uppercase tracking-wider mb-0.5">Nome</p>
              {editingNome ? (
                <input
                  autoFocus
                  value={nomeLocal}
                  onChange={e => setNomeLocal(e.target.value)}
                  onBlur={handleNomeSave}
                  onKeyDown={e => { if (e.key === 'Enter') handleNomeSave() }}
                  className="bg-transparent font-mono text-sm text-gray-100 border-b border-emerald-400 focus:outline-none w-full"
                />
              ) : (
                <p
                  onClick={() => { setNomeLocal(projeto.projeto_nome); setEditingNome(true) }}
                  className="text-sm font-mono text-gray-100 cursor-text hover:text-white"
                >
                  {projeto.projeto_nome}
                </p>
              )}
            </div>

            {/* Status — select inline */}
            <div>
              <p className="text-[10px] font-mono text-gray-600 uppercase tracking-wider mb-0.5">Status</p>
              <select
                value={projeto.status}
                onChange={handleStatusChange}
                className="bg-gray-950 border border-gray-800 rounded-lg px-2 py-1.5 text-sm font-mono text-gray-100 focus:outline-none focus:border-gray-600 cursor-pointer"
              >
                {statusOpcoes.map(s => (
                  <option key={s} value={s} className="bg-gray-900">
                    {STATUS_CFG[s]?.label ?? s}
                  </option>
                ))}
              </select>
            </div>

            {/* Receita mensal — inline edit */}
            <div>
              <p className="text-[10px] font-mono text-gray-600 uppercase tracking-wider mb-0.5">Receita mensal</p>
              {editingReceita ? (
                <input
                  autoFocus
                  type="number"
                  step="0.01"
                  min="0"
                  value={receitaLocal}
                  onChange={e => setReceitaLocal(e.target.value)}
                  onBlur={handleReceitaSave}
                  onKeyDown={e => { if (e.key === 'Enter') handleReceitaSave() }}
                  className="bg-transparent font-mono text-sm text-gray-100 border-b border-emerald-400 focus:outline-none w-full"
                />
              ) : (
                <p
                  onClick={handleReceitaEdit}
                  className="text-sm font-mono text-gray-100 cursor-text hover:text-white"
                >
                  {projeto.receita_mensal != null
                    ? <>{projeto.receita_mensal.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })} <span className="text-gray-700 text-[10px]">(clique para editar)</span></>
                    : <span className="text-gray-700 italic">— clique para editar</span>
                  }
                </p>
              )}
            </div>

            {/* Tipo — read-only */}
            <div>
              <p className="text-[10px] font-mono text-gray-600 uppercase tracking-wider mb-0.5">Tipo</p>
              <span className={`text-xs font-mono px-2 py-0.5 rounded-full ${tipo.cls}`}>{tipo.label}</span>
            </div>

            {/* Criado em */}
            <div>
              <p className="text-[10px] font-mono text-gray-600 uppercase tracking-wider mb-0.5">Criado em</p>
              <p className="text-sm font-mono text-gray-300">
                {new Date(projeto.created_at).toLocaleDateString('pt-BR', { day: '2-digit', month: 'long', year: 'numeric' })}
              </p>
            </div>

          </div>
        </section>

        {/* Bloco: Detalhes do tipo */}
        <section className="bg-gray-900 border border-gray-800 rounded-lg p-5">
          <h2 className="text-xs font-mono font-semibold uppercase tracking-wider text-gray-600 mb-4">
            Detalhes do tipo
          </h2>
          <MetadataSection projeto={projeto} onSave={handleInlineUpdate} />
        </section>

        {/* Bloco: Documentos do Projeto */}
        {(projeto.status === 'publicado' || projeto.tipo === 'rank_rent') && (() => {
          const s = projeto.status
          const completed = (name: string) => executions.some(e => e.agent_name === name && e.status === 'completed')
          const hasIntel           = completed('competitive_intel')
          const hasCompetitorAudit = completed('competitor_audit')
          const hasSeo             = completed('seo_architect')
          const hasAudit           = completed('seo_auditor')

          function DocBtn({ label, path, colorCls, available, aguardando }: {
            label: string; path: string; colorCls: string; available: boolean; aguardando?: string
          }) {
            return (
              <button
                onClick={() => navigate(path)}
                className={`w-full inline-flex items-center justify-between px-4 py-3 rounded-lg text-xs font-mono
                           border transition-colors ${available
                             ? `${colorCls} hover:opacity-90`
                             : 'bg-gray-900/40 text-gray-600 border-gray-800 hover:bg-gray-800/40'}`}
              >
                <span className="flex items-center gap-2">
                  <span className={`w-1.5 h-1.5 rounded-full ${available ? 'bg-current' : 'bg-gray-700'}`} />
                  {label}
                </span>
                <span className="flex items-center gap-2">
                  {!available && aguardando && (
                    <span className="text-[10px] text-gray-700 font-mono">{aguardando}</span>
                  )}
                  <span className={available ? '' : 'text-gray-700'}>→</span>
                </span>
              </button>
            )
          }

          return (
            <section className="bg-gray-900 border border-gray-800 rounded-lg p-5">
              <h2 className="text-xs font-mono font-semibold uppercase tracking-wider text-gray-600 mb-4">
                Documentos do Projeto
              </h2>
              <div className="space-y-2">
                <DocBtn
                  label="Pipeline de Agentes"
                  path={`/projetos/${projeto.id}/pipeline`}
                  colorCls="bg-slate-500/10 text-slate-400 border-slate-500/30"
                  available={true}
                />
                <DocBtn
                  label="Plano de SEO"
                  path={`/projetos/${projeto.id}/seo-plan`}
                  colorCls="bg-blue-500/10 text-blue-400 border-blue-500/30"
                  available={hasIntel}
                  aguardando="/competitive-intel"
                />
                <DocBtn
                  label="Análise de Concorrentes"
                  path={`/projetos/${projeto.id}/competitor-audit`}
                  colorCls="bg-orange-500/10 text-orange-400 border-orange-500/30"
                  available={hasCompetitorAudit}
                  aguardando="/competitor-audit"
                />
                <DocBtn
                  label="Conteúdo"
                  path={`/projetos/${projeto.id}/content`}
                  colorCls="bg-violet-500/10 text-violet-400 border-violet-500/30"
                  available={hasSeo}
                  aguardando="/seo-architect"
                />
                <DocBtn
                  label="Auditoria SEO"
                  path={`/projetos/${projeto.id}/auditoria`}
                  colorCls="bg-cyan-500/10 text-cyan-400 border-cyan-500/30"
                  available={hasAudit}
                  aguardando="/seo-auditor"
                />
                {s === 'publicado' && (
                  <DocBtn
                    label="Ver Ranking"
                    path={`/projetos/${projeto.id}/ranking`}
                    colorCls="bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
                    available={true}
                  />
                )}
                {s === 'publicado' && (
                  <DocBtn
                    label="Relatório"
                    path={`/projetos/${projeto.id}/relatorio`}
                    colorCls="bg-amber-500/10 text-amber-400 border-amber-500/30"
                    available={true}
                  />
                )}
              </div>
            </section>
          )
        })()}

        {/* Bloco: Funil de leads (prospeccao only) */}
        {projeto.tipo === 'prospeccao' && (
          <section className="bg-gray-900 border border-gray-800 rounded-lg p-5">
            <h2 className="text-xs font-mono font-semibold uppercase tracking-wider text-gray-600 mb-4">
              Funil de Prospecção
            </h2>
            <p className="text-sm font-mono text-gray-500 mb-4">
              Leads do ciclo Achou → Refez → Publicou → Ofertou, gravados pelos agentes do plugin prospector.
            </p>
            <button
              onClick={() => navigate(`/projetos/${projeto.id}/prospeccao`)}
              className="px-4 py-2 text-sm font-mono bg-amber-600 text-white rounded-lg hover:bg-amber-500"
            >
              Abrir funil de leads →
            </button>
          </section>
        )}

        {/* Bloco: Planos de Palavras-chave (rank_rent only) */}
        {projeto.tipo === 'rank_rent' && (
          <PesquisasSection projeto={projeto} onVinculada={handleVincular} />
        )}

        {/* Bloco: Histórico de execuções */}
        {projeto.tipo === 'rank_rent' && (
          <HistoricoSection projetoId={projeto.id} />
        )}

        {/* Zona de Perigo */}
        <section className="border border-red-500/20 rounded-lg p-5">
          <h2 className="text-xs font-mono font-semibold uppercase tracking-wider text-gray-600 mb-4">
            Zona de Perigo
          </h2>
          <button
            onClick={handleDelete}
            disabled={deleting}
            className="text-sm font-mono text-red-500 border border-red-500/30 px-4 py-2 rounded-lg hover:bg-red-500/10 disabled:opacity-50 flex items-center gap-2"
          >
            {deleting ? <><Spinner /> Excluindo...</> : 'Excluir projeto'}
          </button>
        </section>

      </main>
    </div>
  )
}
