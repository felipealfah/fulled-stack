import { useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { projetosApi, type Projeto, type ProjetoTipo, type ProjetoCreate } from '../lib/api'

// ── Config objetos (padrão KwPlannerGate2) ──────────────────────────────────

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

const FILTER_PILLS = [
  { value: 'todos', label: 'Todos' },
  { value: 'rank_rent', label: 'Rank & Rent' },
  { value: 'infoproduto', label: 'Infoproduto' },
  { value: 'youtube_faceless', label: 'YouTube' },
  { value: 'facebook_faceless', label: 'Facebook' },
  { value: 'prospeccao', label: 'Prospecção' },
] as const

// ── Helpers ──────────────────────────────────────────────────────────────────

function camposPrincipais(p: Projeto): string {
  const m = p.metadata
  switch (p.tipo) {
    case 'rank_rent':
      return [m.nicho, m.cidade].filter(Boolean).join(' · ') || '—'
    case 'infoproduto':
      return [m.produto, m.plataforma].filter(Boolean).join(' · ') || '—'
    case 'youtube_faceless':
      return m.canal ? `canal: ${m.canal}` : '—'
    case 'facebook_faceless':
      return m.pagina ? `página: ${m.pagina}` : '—'
    case 'prospeccao':
      return [m.nicho, m.cidade].filter(Boolean).join(' · ') || '—'
    default:
      return '—'
  }
}

// ── Inline components ─────────────────────────────────────────────────────────

function Spinner({ size = 'sm' }: { size?: 'sm' | 'md' }) {
  const cls = size === 'sm' ? 'w-3.5 h-3.5' : 'w-5 h-5'
  return (
    <span className={`inline-block ${cls} border border-current border-t-transparent rounded-full animate-spin opacity-60`} />
  )
}

function TrashIcon() {
  return (
    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
    </svg>
  )
}

// ── Campos dinâmicos do formulário ───────────────────────────────────────────

function RankRentFields({ meta, onChange }: { meta: Record<string, string>; onChange: (k: string, v: string) => void }) {
  return (
    <>
      {[
        { key: 'nicho', label: 'Nicho', placeholder: 'Ex: encanador', required: true },
        { key: 'cidade', label: 'Cidade', placeholder: 'Ex: Brasília DF', required: true },
        { key: 'site_url', label: 'URL do site (opcional)', placeholder: 'https://...', required: false },
      ].map(f => (
        <div key={f.key}>
          <label className="text-xs font-mono text-gray-500 mb-1.5 block">{f.label}</label>
          <input
            type="text"
            value={meta[f.key] ?? ''}
            onChange={e => onChange(f.key, e.target.value)}
            placeholder={f.placeholder}
            required={f.required}
            className="bg-gray-950 border border-gray-800 rounded-lg px-3 py-2.5 text-sm font-mono text-gray-100 placeholder-gray-700 focus:outline-none focus:border-gray-600 w-full"
          />
        </div>
      ))}
    </>
  )
}

function InfoprodutoFields({ meta, onChange }: { meta: Record<string, string>; onChange: (k: string, v: string) => void }) {
  return (
    <>
      <div>
        <label className="text-xs font-mono text-gray-500 mb-1.5 block">Produto</label>
        <input type="text" value={meta.produto ?? ''} onChange={e => onChange('produto', e.target.value)} placeholder="Nome do produto" required className="bg-gray-950 border border-gray-800 rounded-lg px-3 py-2.5 text-sm font-mono text-gray-100 placeholder-gray-700 focus:outline-none focus:border-gray-600 w-full" />
      </div>
      <div>
        <label className="text-xs font-mono text-gray-500 mb-1.5 block">Plataforma</label>
        <select value={meta.plataforma ?? ''} onChange={e => onChange('plataforma', e.target.value)} required className="bg-gray-950 border border-gray-800 rounded-lg px-3 py-2.5 text-sm font-mono text-gray-100 focus:outline-none focus:border-gray-600 w-full cursor-pointer">
          <option value="" className="bg-gray-900">Selecione</option>
          {['Hotmart', 'Eduzz', 'Kiwify'].map(p => <option key={p} value={p} className="bg-gray-900">{p}</option>)}
        </select>
      </div>
      <div>
        <label className="text-xs font-mono text-gray-500 mb-1.5 block">Nicho</label>
        <input type="text" value={meta.nicho ?? ''} onChange={e => onChange('nicho', e.target.value)} placeholder="Ex: finanças pessoais" required className="bg-gray-950 border border-gray-800 rounded-lg px-3 py-2.5 text-sm font-mono text-gray-100 placeholder-gray-700 focus:outline-none focus:border-gray-600 w-full" />
      </div>
    </>
  )
}

function YouTubeFields({ meta, onChange }: { meta: Record<string, string>; onChange: (k: string, v: string) => void }) {
  return (
    <>
      <div>
        <label className="text-xs font-mono text-gray-500 mb-1.5 block">Nome do canal</label>
        <input type="text" value={meta.canal ?? ''} onChange={e => onChange('canal', e.target.value)} placeholder="Ex: @meucanal" required className="bg-gray-950 border border-gray-800 rounded-lg px-3 py-2.5 text-sm font-mono text-gray-100 placeholder-gray-700 focus:outline-none focus:border-gray-600 w-full" />
      </div>
      <div>
        <label className="text-xs font-mono text-gray-500 mb-1.5 block">Nicho</label>
        <input type="text" value={meta.nicho ?? ''} onChange={e => onChange('nicho', e.target.value)} placeholder="Ex: culinária" required className="bg-gray-950 border border-gray-800 rounded-lg px-3 py-2.5 text-sm font-mono text-gray-100 placeholder-gray-700 focus:outline-none focus:border-gray-600 w-full" />
      </div>
      <div>
        <label className="text-xs font-mono text-gray-500 mb-1.5 block">Idioma</label>
        <select value={meta.idioma ?? ''} onChange={e => onChange('idioma', e.target.value)} required className="bg-gray-950 border border-gray-800 rounded-lg px-3 py-2.5 text-sm font-mono text-gray-100 focus:outline-none focus:border-gray-600 w-full cursor-pointer">
          <option value="" className="bg-gray-900">Selecione</option>
          {['PT-BR', 'EN', 'ES'].map(i => <option key={i} value={i} className="bg-gray-900">{i}</option>)}
        </select>
      </div>
    </>
  )
}

function FacebookFields({ meta, onChange }: { meta: Record<string, string>; onChange: (k: string, v: string) => void }) {
  return (
    <>
      <div>
        <label className="text-xs font-mono text-gray-500 mb-1.5 block">Nome da página</label>
        <input type="text" value={meta.pagina ?? ''} onChange={e => onChange('pagina', e.target.value)} placeholder="Ex: Receitas Fit BR" required className="bg-gray-950 border border-gray-800 rounded-lg px-3 py-2.5 text-sm font-mono text-gray-100 placeholder-gray-700 focus:outline-none focus:border-gray-600 w-full" />
      </div>
      <div>
        <label className="text-xs font-mono text-gray-500 mb-1.5 block">Nicho</label>
        <input type="text" value={meta.nicho ?? ''} onChange={e => onChange('nicho', e.target.value)} placeholder="Ex: alimentação saudável" required className="bg-gray-950 border border-gray-800 rounded-lg px-3 py-2.5 text-sm font-mono text-gray-100 placeholder-gray-700 focus:outline-none focus:border-gray-600 w-full" />
      </div>
      <div>
        <label className="text-xs font-mono text-gray-500 mb-1.5 block">Formato</label>
        <select value={meta.formato ?? ''} onChange={e => onChange('formato', e.target.value)} required className="bg-gray-950 border border-gray-800 rounded-lg px-3 py-2.5 text-sm font-mono text-gray-100 focus:outline-none focus:border-gray-600 w-full cursor-pointer">
          <option value="" className="bg-gray-900">Selecione</option>
          {['reels', 'posts', 'mix'].map(f => <option key={f} value={f} className="bg-gray-900">{f}</option>)}
        </select>
      </div>
    </>
  )
}

function ProspeccaoFields({ meta, onChange }: { meta: Record<string, string>; onChange: (k: string, v: string) => void }) {
  return (
    <>
      {[
        { key: 'nicho', label: 'Nicho', placeholder: 'Ex: dentista', required: true },
        { key: 'cidade', label: 'Cidade', placeholder: 'Ex: Brasília DF', required: true },
      ].map(f => (
        <div key={f.key}>
          <label className="text-xs font-mono text-gray-500 mb-1.5 block">{f.label}</label>
          <input
            type="text"
            value={meta[f.key] ?? ''}
            onChange={e => onChange(f.key, e.target.value)}
            placeholder={f.placeholder}
            required={f.required}
            className="bg-gray-950 border border-gray-800 rounded-lg px-3 py-2.5 text-sm font-mono text-gray-100 placeholder-gray-700 focus:outline-none focus:border-gray-600 w-full"
          />
        </div>
      ))}
    </>
  )
}

// ── Modal de criação ──────────────────────────────────────────────────────────

function NovoProjetoModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [nome, setNome] = useState('')
  const [tipo, setTipo] = useState<ProjetoTipo>('rank_rent')
  const [meta, setMeta] = useState<Record<string, string>>({})
  const [submitting, setSubmitting] = useState(false)
  const [erro, setErro] = useState('')

  function handleMetaChange(k: string, v: string) {
    setMeta(prev => ({ ...prev, [k]: v }))
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setErro('')
    try {
      const data: ProjetoCreate = { projeto_nome: nome, tipo, metadata: meta }
      await projetosApi.create(data)
      onCreated()
      onClose()
    } catch {
      setErro('Erro ao criar projeto. Verifique os campos e tente novamente.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-40 bg-black/70 backdrop-blur-sm flex items-center justify-center">
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-8 max-w-md w-full mx-4 relative">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-gray-600 hover:text-gray-300 font-mono text-sm"
        >
          ×
        </button>
        <h2 className="font-mono font-semibold text-gray-100 mb-1">Novo Projeto</h2>
        <p className="text-xs font-mono text-gray-600 mb-6">Preencha os dados do projeto</p>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          {/* Campos comuns */}
          <div>
            <label className="text-xs font-mono text-gray-500 mb-1.5 block">Nome do projeto</label>
            <input
              type="text"
              value={nome}
              onChange={e => setNome(e.target.value)}
              placeholder="Ex: Encanador Brasília DF"
              required
              className="bg-gray-950 border border-gray-800 rounded-lg px-3 py-2.5 text-sm font-mono text-gray-100 placeholder-gray-700 focus:outline-none focus:border-gray-600 w-full"
            />
          </div>
          <div>
            <label className="text-xs font-mono text-gray-500 mb-1.5 block">Tipo de projeto</label>
            <select
              value={tipo}
              onChange={e => { setTipo(e.target.value as ProjetoTipo); setMeta({}) }}
              className="bg-gray-950 border border-gray-800 rounded-lg px-3 py-2.5 text-sm font-mono text-gray-100 focus:outline-none focus:border-gray-600 w-full cursor-pointer"
            >
              <option value="rank_rent" className="bg-gray-900">Rank &amp; Rent</option>
              <option value="infoproduto" className="bg-gray-900">Infoproduto</option>
              <option value="youtube_faceless" className="bg-gray-900">YouTube Faceless</option>
              <option value="facebook_faceless" className="bg-gray-900">Facebook Faceless</option>
              <option value="prospeccao" className="bg-gray-900">Prospecção (Outbound)</option>
            </select>
          </div>

          {/* Campos dinâmicos por tipo */}
          {tipo === 'rank_rent' && <RankRentFields meta={meta} onChange={handleMetaChange} />}
          {tipo === 'infoproduto' && <InfoprodutoFields meta={meta} onChange={handleMetaChange} />}
          {tipo === 'youtube_faceless' && <YouTubeFields meta={meta} onChange={handleMetaChange} />}
          {tipo === 'facebook_faceless' && <FacebookFields meta={meta} onChange={handleMetaChange} />}
          {tipo === 'prospeccao' && <ProspeccaoFields meta={meta} onChange={handleMetaChange} />}

          {/* Erro */}
          {erro && <p className="text-xs font-mono text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">{erro}</p>}

          {/* Footer */}
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
              disabled={submitting}
              className="px-4 py-2 text-sm font-mono bg-emerald-600 text-white rounded-lg hover:bg-emerald-500 disabled:opacity-30 flex items-center gap-2"
            >
              {submitting ? <><Spinner /> Criando...</> : 'Criar Projeto →'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Componente principal ──────────────────────────────────────────────────────

export function Projetos() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [tipoFiltro, setTipoFiltro] = useState<string>('todos')
  const [showModal, setShowModal] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['projetos'],
    queryFn: () => projetosApi.list(),
    refetchInterval: 10000, // agentes criam campanhas via API — refletir sem F5
  })

  const projetos = useMemo(() => {
    if (!data) return []
    if (tipoFiltro === 'todos') return data
    return data.filter(p => p.tipo === tipoFiltro)
  }, [data, tipoFiltro])

  async function handleDelete(e: React.MouseEvent, id: string, nome: string) {
    e.stopPropagation()
    if (!confirm(`Excluir o projeto "${nome}"? Esta ação não pode ser desfeita.`)) return
    setDeletingId(id)
    try {
      await projetosApi.delete(id)
      queryClient.invalidateQueries({ queryKey: ['projetos'] })
    } catch {
      // silent
    } finally {
      setDeletingId(null)
    }
  }

  if (isLoading) return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center">
      <div className="flex items-center gap-2.5 text-gray-600 text-sm font-mono">
        <Spinner size="md" /> Carregando projetos...
      </div>
    </div>
  )

  if (error) return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center">
      <p className="text-red-400 text-sm font-mono">Erro ao carregar projetos. Verifique a conexão com a API.</p>
    </div>
  )

  return (
    <div className="min-h-screen bg-gray-950">
      {showModal && (
        <NovoProjetoModal
          onClose={() => setShowModal(false)}
          onCreated={() => queryClient.invalidateQueries({ queryKey: ['projetos'] })}
        />
      )}

      {/* Header */}
      <header className="border-b border-gray-800 px-6 py-5">
        <div className="max-w-3xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse shrink-0" />
            <div>
              <h1 className="font-mono font-semibold tracking-tight text-gray-100">Projetos</h1>
              <p className="text-xs text-gray-600 font-mono mt-0.5">{data?.length ?? 0} projetos</p>
            </div>
          </div>
          <button
            onClick={() => setShowModal(true)}
            className="px-4 py-2 text-sm font-mono bg-emerald-600 text-white rounded-lg hover:bg-emerald-500"
          >
            + Novo Projeto
          </button>
        </div>
      </header>

      {/* Filter pills */}
      <div className="px-6 pt-6 pb-4">
        <div className="max-w-3xl mx-auto flex items-center gap-2 flex-wrap">
          {FILTER_PILLS.map(pill => (
            <button
              key={pill.value}
              onClick={() => setTipoFiltro(pill.value)}
              className={
                tipoFiltro === pill.value
                  ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 px-3 py-1.5 text-xs font-mono rounded-full'
                  : 'text-gray-500 border border-gray-800 hover:text-gray-300 hover:border-gray-700 px-3 py-1.5 text-xs font-mono rounded-full'
              }
            >
              {pill.label}
            </button>
          ))}
        </div>
      </div>

      {/* Cards */}
      <div className="max-w-3xl mx-auto px-6 pb-8">
        {projetos.length === 0 ? (
          <div className="flex flex-col items-center gap-4 py-16 text-center">
            {tipoFiltro === 'todos' ? (
              <>
                <h2 className="font-mono font-semibold text-gray-400">Nenhum projeto cadastrado</h2>
                <p className="font-mono text-sm text-gray-600 max-w-sm">Crie o primeiro projeto para começar a gerenciar seu portfólio.</p>
                <button onClick={() => setShowModal(true)} className="px-4 py-2 text-sm font-mono bg-emerald-600 text-white rounded-lg hover:bg-emerald-500">
                  + Novo Projeto
                </button>
              </>
            ) : (
              <>
                <h2 className="font-mono font-semibold text-gray-400">
                  Nenhum projeto do tipo {FILTER_PILLS.find(p => p.value === tipoFiltro)?.label}
                </h2>
                <p className="font-mono text-sm text-gray-600 max-w-sm">Mude o filtro ou crie um novo projeto.</p>
              </>
            )}
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {projetos.map(p => {
              const tipo = TIPO_CFG[p.tipo] ?? { label: p.tipo, cls: 'bg-gray-800 text-gray-500 border border-gray-700' }
              const status = STATUS_CFG[p.status] ?? { label: p.status, cls: 'bg-gray-800 text-gray-500 border border-gray-700' }
              return (
                <div key={p.id} className="relative group">
                  <button
                    onClick={() => navigate(`/projetos/${p.id}`)}
                    className="w-full text-left bg-gray-900 border border-gray-800 rounded-lg px-5 py-4 hover:border-gray-700 hover:bg-gray-800/60 transition-all duration-150"
                  >
                    <div className="flex items-center justify-between gap-3 pr-8">
                      <span className="font-mono font-semibold text-gray-100 group-hover:text-white truncate">
                        {p.projeto_nome}
                      </span>
                      <span className={`text-xs font-mono px-2 py-0.5 rounded-full whitespace-nowrap shrink-0 ${tipo.cls}`}>
                        {tipo.label}
                      </span>
                    </div>
                    <div className="text-xs font-mono text-gray-600 mt-1">{camposPrincipais(p)}</div>
                    <div className="flex items-center gap-3 mt-2 text-xs font-mono text-gray-700">
                      <span className={`px-1.5 py-0.5 rounded text-[10px] ${status.cls}`}>{status.label}</span>
                      <span>{new Date(p.created_at).toLocaleDateString('pt-BR')}</span>
                    </div>
                  </button>
                  <button
                    onClick={e => handleDelete(e, p.id, p.projeto_nome)}
                    disabled={deletingId === p.id}
                    className="absolute right-3 top-1/2 -translate-y-1/2 p-1.5 rounded text-gray-700 hover:text-red-400 hover:bg-red-500/10 opacity-0 group-hover:opacity-100 transition-all disabled:opacity-50"
                    title="Excluir projeto"
                  >
                    {deletingId === p.id ? <Spinner /> : <TrashIcon />}
                  </button>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
