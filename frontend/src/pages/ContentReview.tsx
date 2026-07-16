import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'
import { contentApi, projetosApi, type ContentPage, type SectionResult } from '../lib/api'

// Chips de status de página (UI-SPEC)
const STATUS_CHIP: Record<string, string> = {
  gerado:   'bg-gray-800 text-gray-500 border border-gray-700',
  revisado: 'bg-amber-500/10 text-amber-400 border border-amber-500/25',
  aprovado: 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30',
  revisar:  'bg-red-500/10 text-red-400 border border-red-500/25',
}

// Chips de status de seção D-03 (UI-SPEC)
const SECTION_CHIP: Record<string, string> = {
  ok:      'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
  ajustar: 'bg-amber-500/10 text-amber-400 border-amber-500/25',
  flag:    'bg-amber-500/10 text-amber-400 border-amber-500/25',
  refazer: 'bg-red-500/10 text-red-400 border-red-500/25',
}

// Chips de page_type (UI-SPEC)
const PAGE_TYPE_CHIP: Record<string, string> = {
  home:           'bg-blue-500/10 text-blue-400 border-blue-500/30',
  service:        'bg-violet-500/10 text-violet-400 border-violet-500/30',
  service_region: 'bg-violet-500/10 text-violet-400 border-violet-500/30',
}

// Rótulos de page_type
const PAGE_TYPE_LABEL: Record<string, string> = {
  home:           'home',
  service:        'service',
  service_region: 'service+região',
}

const STATUS_OPTIONS: ContentPage['status'][] = ['gerado', 'revisado', 'aprovado', 'revisar']
const SECTION_STATUS_OPTIONS = ['ok', 'ajustar', 'flag', 'refazer'] as const

interface SectionRowProps {
  secName: string
  sec: SectionResult
  projetoId: string
  pageSlug: string
}

function SectionRow({ secName, sec, projetoId, pageSlug }: SectionRowProps) {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [editStatus, setEditStatus] = useState(sec.status)
  const [editIssues, setEditIssues] = useState((sec.issues ?? []).join('\n'))
  const [confirmDeleteSec, setConfirmDeleteSec] = useState(false)

  const mutation = useMutation({
    mutationFn: () => contentApi.updateSection(
      projetoId,
      pageSlug,
      secName,
      editStatus,
      editIssues.split('\n').map(s => s.trim()).filter(Boolean),
    ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['content-pages', String(projetoId)] })
      setEditing(false)
    },
  })

  const deleteSectionMutation = useMutation({
    mutationFn: () => contentApi.deleteSection(projetoId, pageSlug, secName),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['content-pages', String(projetoId)] }),
  })

  if (editing) {
    return (
      <tr className="border-b border-gray-800/30 bg-gray-800/20">
        <td />
        <td className="pl-8 pr-2 py-2 text-[10px] font-mono text-gray-500 align-top">{secName}</td>
        <td className="px-2 py-2 align-top">
          <div className="flex gap-1">
            {SECTION_STATUS_OPTIONS.map(opt => (
              <button
                key={opt}
                onClick={() => setEditStatus(opt)}
                className={`px-1.5 py-0.5 rounded border text-[10px] font-mono transition-colors ${
                  editStatus === opt
                    ? SECTION_CHIP[opt] + ' ring-1 ring-inset ring-current'
                    : 'bg-gray-800/50 text-gray-600 border-gray-700 hover:bg-gray-800'
                }`}
              >
                {opt}
              </button>
            ))}
          </div>
        </td>
        <td className="px-2 py-2" colSpan={2}>
          <textarea
            value={editIssues}
            onChange={e => setEditIssues(e.target.value)}
            rows={2}
            placeholder="Uma observação por linha (deixe vazio para nenhuma)"
            className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-[10px] font-mono text-gray-300 placeholder-gray-600 resize-none focus:outline-none focus:border-gray-600"
          />
        </td>
        <td className="px-3 py-2 align-top">
          <div className="flex gap-1 justify-end">
            <button
              onClick={() => mutation.mutate()}
              disabled={mutation.isPending}
              className="px-2 py-1 text-[10px] font-mono bg-blue-500/10 text-blue-400 border border-blue-500/30 rounded hover:bg-blue-500/20 disabled:opacity-40 transition-colors"
            >
              {mutation.isPending ? '...' : 'Salvar'}
            </button>
            <button
              onClick={() => { setEditing(false); setEditStatus(sec.status); setEditIssues((sec.issues ?? []).join('\n')) }}
              className="px-2 py-1 text-[10px] font-mono text-gray-600 border border-gray-700 rounded hover:bg-gray-800 transition-colors"
            >
              ✕
            </button>
          </div>
        </td>
      </tr>
    )
  }

  return (
    <tr className="border-b border-gray-800/30 bg-gray-900/30 group">
      <td />
      <td className="pl-8 pr-4 py-1.5 text-[10px] font-mono text-gray-600">{secName}</td>
      <td className="px-4 py-1.5">
        <span className={`inline-flex items-center px-1.5 py-0.5 rounded border text-[10px] font-mono ${SECTION_CHIP[sec.status] ?? ''}`}>
          {sec.status}
        </span>
      </td>
      <td className="px-4 py-1.5" colSpan={2}>
        {sec.issues && sec.issues.length > 0 && (
          <span className="text-[10px] font-mono text-gray-500 italic">
            {sec.issues.join(' · ')}
          </span>
        )}
      </td>
      <td className="px-3 py-1.5 text-right">
        <div className="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 transition-all">
          <button
            onClick={() => setEditing(true)}
            title="Editar seção"
            className="px-2 py-0.5 text-[10px] font-mono text-gray-600 border border-gray-700 rounded hover:bg-gray-800 hover:text-gray-300 transition-colors"
          >
            ✎
          </button>
          {confirmDeleteSec ? (
            <>
              <button
                onClick={() => deleteSectionMutation.mutate()}
                disabled={deleteSectionMutation.isPending}
                className="px-2 py-0.5 text-[10px] font-mono bg-red-500/10 text-red-400 border border-red-500/30 rounded hover:bg-red-500/20 disabled:opacity-40 transition-colors"
              >
                {deleteSectionMutation.isPending ? '...' : 'Apagar'}
              </button>
              <button
                onClick={() => setConfirmDeleteSec(false)}
                className="px-1.5 py-0.5 text-[10px] font-mono text-gray-600 border border-gray-700 rounded hover:bg-gray-800 transition-colors"
              >
                ✕
              </button>
            </>
          ) : (
            <button
              onClick={() => setConfirmDeleteSec(true)}
              title="Apagar seção"
              className="px-2 py-0.5 text-[10px] font-mono text-gray-600 border border-gray-700 rounded hover:bg-red-500/10 hover:text-red-400 hover:border-red-500/30 transition-colors"
            >
              ✕
            </button>
          )}
        </div>
      </td>
    </tr>
  )
}

interface EditStatusModalProps {
  page: ContentPage
  projetoId: string
  onClose: () => void
  onSaved: () => void
}

function EditStatusModal({ page, projetoId, onClose, onSaved }: EditStatusModalProps) {
  const [selected, setSelected] = useState<ContentPage['status']>(page.status)
  const queryClient = useQueryClient()

  const mutation = useMutation({
    mutationFn: () => contentApi.updateStatus(projetoId, page.page_slug, selected),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['content-pages', String(projetoId)] })
      onSaved()
    },
  })

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div
        className="bg-gray-900 border border-gray-700 rounded-xl p-6 w-80 space-y-4"
        onClick={e => e.stopPropagation()}
      >
        <h2 className="text-xs font-mono font-semibold uppercase tracking-wider text-gray-400">
          Editar status — <span className="text-gray-200">{page.page_slug}</span>
        </h2>
        <div className="space-y-2">
          {STATUS_OPTIONS.map(opt => (
            <button
              key={opt}
              onClick={() => setSelected(opt)}
              className={`w-full text-left px-3 py-2 rounded-lg border text-[10px] font-mono transition-colors ${
                selected === opt
                  ? STATUS_CHIP[opt] + ' ring-1 ring-inset ring-current'
                  : 'bg-gray-800/50 text-gray-500 border-gray-700 hover:bg-gray-800'
              }`}
            >
              {opt}
            </button>
          ))}
        </div>
        <div className="flex gap-2 pt-1">
          <button
            onClick={onClose}
            className="flex-1 px-3 py-2 text-[10px] font-mono text-gray-500 border border-gray-700 rounded-lg hover:bg-gray-800 transition-colors"
          >
            Cancelar
          </button>
          <button
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending || selected === page.status}
            className="flex-1 px-3 py-2 text-[10px] font-mono bg-blue-500/10 text-blue-400 border border-blue-500/30 rounded-lg hover:bg-blue-500/20 disabled:opacity-40 transition-colors"
          >
            {mutation.isPending ? 'Salvando...' : 'Salvar'}
          </button>
        </div>
        {mutation.isError && (
          <p className="text-[10px] font-mono text-red-400">Erro ao salvar. Tente novamente.</p>
        )}
      </div>
    </div>
  )
}

interface PageRowProps {
  page: ContentPage
  projetoId: string
  onDeleted: () => void
}

function PageRow({ page, projetoId, onDeleted }: PageRowProps) {
  const queryClient = useQueryClient()
  const [expanded, setExpanded] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const deleteMutation = useMutation({
    mutationFn: () => contentApi.delete(projetoId, page.page_slug),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['content-pages', String(projetoId)] })
      onDeleted()
    },
  })

  const sections = page.review_report?.sections ?? {}
  const sectionNames = Object.keys(sections)

  return (
    <>
      {editOpen && (
        <EditStatusModal
          page={page}
          projetoId={projetoId}
          onClose={() => setEditOpen(false)}
          onSaved={() => setEditOpen(false)}
        />
      )}
      <tr
        className="border-b border-gray-800/60 hover:bg-gray-800/30 transition-colors cursor-pointer"
        onClick={() => sectionNames.length > 0 && setExpanded(e => !e)}
      >
        {/* Expand */}
        <td
          className="px-3 py-3 text-[10px] font-mono text-gray-600 w-4 select-none"
          aria-label={expanded ? 'Recolher seções' : 'Expandir seções'}
        >
          {sectionNames.length > 0 ? (expanded ? '▼' : '▶') : ''}
        </td>
        {/* Slug */}
        <td className="px-4 py-3 text-xs font-mono text-gray-200">
          {page.page_slug}
        </td>
        {/* Tipo */}
        <td className="px-4 py-3 w-[120px]">
          <span className={`inline-flex items-center px-2 py-0.5 rounded border text-[10px] font-mono ${PAGE_TYPE_CHIP[page.page_type] ?? ''}`}>
            {PAGE_TYPE_LABEL[page.page_type] ?? page.page_type}
          </span>
        </td>
        {/* Status */}
        <td className="px-4 py-3 w-[112px]">
          <span className={`inline-flex items-center px-2 py-0.5 rounded-full border text-[10px] font-mono ${STATUS_CHIP[page.status] ?? ''}`}>
            {page.status}
          </span>
        </td>
        {/* Revisado em */}
        <td className="px-4 py-3 w-[120px] text-[10px] font-mono text-gray-600">
          {page.reviewed_at
            ? new Date(page.reviewed_at).toLocaleDateString('pt-BR')
            : '—'}
        </td>
        {/* Ações */}
        <td className="px-4 py-3 w-[180px] text-right" onClick={e => e.stopPropagation()}>
          <div className="flex items-center justify-end gap-1.5">
            {/* Editar status */}
            <button
              onClick={() => setEditOpen(true)}
              title="Editar status"
              className="px-2 py-1.5 text-[10px] font-mono text-gray-500 border border-gray-700 rounded-lg hover:bg-gray-800 hover:text-gray-300 transition-colors"
            >
              ✎
            </button>
            {/* Apagar */}
            {confirmDelete ? (
              <div className="flex gap-1">
                <button
                  onClick={() => deleteMutation.mutate()}
                  disabled={deleteMutation.isPending}
                  className="px-2 py-1.5 text-[10px] font-mono bg-red-500/10 text-red-400 border border-red-500/30 rounded-lg hover:bg-red-500/20 disabled:opacity-40 transition-colors"
                >
                  {deleteMutation.isPending ? '...' : 'Confirmar'}
                </button>
                <button
                  onClick={() => setConfirmDelete(false)}
                  className="px-2 py-1.5 text-[10px] font-mono text-gray-600 border border-gray-700 rounded-lg hover:bg-gray-800 transition-colors"
                >
                  ✕
                </button>
              </div>
            ) : (
              <button
                onClick={() => setConfirmDelete(true)}
                title="Apagar página"
                className="px-2 py-1.5 text-[10px] font-mono text-gray-600 border border-gray-700 rounded-lg hover:bg-red-500/10 hover:text-red-400 hover:border-red-500/30 transition-colors"
              >
                ✕
              </button>
            )}
          </div>
        </td>
      </tr>
      {/* Sub-linhas por seção D-03 */}
      {expanded && sectionNames.map(secName => (
        <SectionRow
          key={secName}
          secName={secName}
          sec={sections[secName]}
          projetoId={projetoId}
          pageSlug={page.page_slug}
        />
      ))}
    </>
  )
}

export function ContentReview() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const projetoId = id!

  const { data: pages, isLoading, isError, refetch } = useQuery<ContentPage[]>({
    queryKey: ['content-pages', id],
    queryFn: () => contentApi.list(projetoId),
    retry: false,
    staleTime: 0,
    refetchOnWindowFocus: true,
  })

  const { data: projeto } = useQuery({
    queryKey: ['projeto', id],
    queryFn: () => projetosApi.get(projetoId),
    staleTime: 60_000,
  })

  const slug = (projeto?.metadata as Record<string, string> | undefined)?.slug
    ?? (projeto?.nicho ?? '').toLowerCase().replace(/\s+/g, '-')

  const total = (pages ?? []).length
  const aprovadas = (pages ?? []).filter(p => p.status === 'aprovado').length
  const revisadas = (pages ?? []).filter(p => p.status === 'revisado').length
  const pendentes = (pages ?? []).filter(p => p.status === 'gerado' || p.status === 'revisar').length
  const readyForSiteBuilder = total > 0 && pendentes === 0
  const allApproved = aprovadas === total && total > 0

  if (isLoading) {
    return (
      <div className="min-h-full bg-gray-950 flex items-center justify-center">
        <p className="text-gray-500 font-mono text-sm">Carregando páginas...</p>
      </div>
    )
  }

  if (isError && !pages) {
    return (
      <div className="min-h-full bg-gray-950 flex items-center justify-center">
        <p className="text-red-400 font-mono text-sm">Erro ao carregar páginas de conteúdo. Tente recarregar a página.</p>
      </div>
    )
  }

  return (
    <div className="min-h-full bg-gray-950">
      {/* Header sticky */}
      <div className="sticky top-0 z-10 border-b border-gray-800 bg-gray-900/50 backdrop-blur-sm">
        <div className="max-w-7xl mx-auto px-6 py-3.5 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button
              onClick={() => navigate(`/projetos/${id}`)}
              className="text-gray-600 hover:text-gray-400 font-mono text-xs transition-colors"
            >
              ← projeto
            </button>
            <h1 className="font-mono text-sm font-semibold text-gray-100">Conteúdo</h1>
          </div>
          <div className="flex items-center gap-3">
            {total > 0 && (
              <span className={`text-[10px] font-mono ${
                allApproved ? 'text-emerald-400' : readyForSiteBuilder ? 'text-amber-400' : 'text-gray-600'
              }`}>
                {allApproved
                  ? `${aprovadas}/${total} aprovados — pronto`
                  : readyForSiteBuilder
                    ? `${revisadas} com flags — revise`
                    : pendentes > 0
                      ? `${pendentes} pendente(s)`
                      : 'Aguardando revisão'}
              </span>
            )}
            <button
              onClick={() => refetch()}
              title="Atualizar dados"
              className="px-2 py-1 text-[10px] font-mono text-gray-600 hover:text-gray-400 border border-gray-800 hover:border-gray-700 rounded transition-colors"
            >
              ↻
            </button>
          </div>
        </div>
      </div>

      {/* Conteúdo principal */}
      <div className="max-w-7xl mx-auto px-6 py-8 space-y-6">
        {/* Banner de prontidão para site-builder */}
        {readyForSiteBuilder && (
          <div className={`rounded-lg border px-4 py-3 font-mono text-xs flex items-center justify-between ${
            allApproved
              ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
              : 'bg-amber-500/10 border-amber-500/30 text-amber-400'
          }`}>
            <span>
              {allApproved
                ? `✓ ${total} página(s) aprovadas — conteúdo pronto para construção`
                : `⚠ ${revisadas} página(s) com flags — revise os apontamentos e aprove para construir`}
            </span>
            <span className="opacity-50 ml-4 shrink-0">
              /site-builder {slug} {projetoId}
            </span>
          </div>
        )}

        {pages && pages.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20">
            <p className="text-sm font-mono text-gray-700 italic">Nenhuma página gerada ainda</p>
            <p className="text-xs font-mono text-gray-700 italic mt-1">
              O agente content_writer precisa gerar o conteúdo antes da revisão.
            </p>
          </div>
        ) : (
          <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
            <table className="w-full text-sm font-mono">
              <thead>
                <tr className="border-b border-gray-800">
                  <th className="px-3 py-3 text-[10px] uppercase tracking-wider text-gray-600 font-mono text-left w-4" />
                  <th className="px-4 py-3 text-[10px] uppercase tracking-wider text-gray-600 font-mono text-left">Página</th>
                  <th className="px-4 py-3 text-[10px] uppercase tracking-wider text-gray-600 font-mono text-left w-[120px]">Tipo</th>
                  <th className="px-4 py-3 text-[10px] uppercase tracking-wider text-gray-600 font-mono text-left w-[112px]">Status</th>
                  <th className="px-4 py-3 text-[10px] uppercase tracking-wider text-gray-600 font-mono text-left w-[120px]">Revisado em</th>
                  <th className="px-4 py-3 text-[10px] uppercase tracking-wider text-gray-600 font-mono text-right w-[120px]">Ação</th>
                </tr>
              </thead>
              <tbody>
                {(pages ?? []).map(page => (
                  <PageRow
                    key={page.id}
                    page={page}
                    projetoId={projetoId}
                    onDeleted={() => refetch()}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
