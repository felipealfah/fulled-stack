import { useState, useMemo, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  fetchOfertasCounts,
  fetchGate,
  fetchAtualizadoEm,
  fetchRastrosCount,
  fetchOfertaByPageId,
  fetchTracker,
  fetchSparklines,
  fetchCandidatas,
  fetchCandidatasTracker,
  fetchInfoapp,
  fetchArquivo,
  fetchRastros,
  insertRastro,
  updateRastro,
  updateOferta,
  insertOferta,
  type Oferta,
  type OfertaStatus,
  type TipoFunil,
  type FormatoEntregavel,
  type ObservacaoDiaria,
  type Rastro,
  type RastroGrupo,
  type RastroStatus,
} from '../lib/lowticket'

// ── Status config ─────────────────────────────────────────────────────────────

const STATUS_CFG = {
  alerta:           { label: 'Alerta',           cls: 'bg-amber-500/20 text-amber-400 border border-amber-500/40' },
  em_analise_funil: { label: 'Em análise',        cls: 'bg-amber-500/10 text-amber-300 border border-amber-500/20' },
  monitorando:      { label: 'Monitorando',       cls: 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30' },
  em_escala:        { label: 'Em escala',         cls: 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40' },
  saturada:         { label: 'Saturada',          cls: 'bg-red-500/10 text-red-400 border border-red-500/30' },
  pausada:          { label: 'Pausada',           cls: 'bg-gray-600/20 text-gray-400 border border-gray-600/30' },
  candidata:        { label: 'Candidata',         cls: 'bg-violet-500/10 text-violet-400 border border-violet-500/30' },
  descartada:       { label: 'Descartada',        cls: 'bg-gray-700/20 text-gray-500 border border-gray-700/30' },
  novo:             { label: 'Novo',              cls: 'bg-gray-600/20 text-gray-400 border border-gray-600/30' },
} as const satisfies Record<OfertaStatus, { label: string; cls: string }>

// ── Tipo das abas ─────────────────────────────────────────────────────────────

type Aba = 'gate' | 'tracker' | 'candidatas' | 'infoapp' | 'arquivo' | 'rastros'

// ── Helpers de formatação ─────────────────────────────────────────────────────

function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit', year: '2-digit' })
}

function fmtMix(video: number | null, imagem: number | null): string {
  if (video == null && imagem == null) return '—'
  const v = video ?? 0
  const i = imagem ?? 0
  return `🎥 ${v} · 🖼 ${i}`
}

// ── Componentes internos ──────────────────────────────────────────────────────

function StatusChip({ status }: { status: OfertaStatus }) {
  const cfg = STATUS_CFG[status] ?? { label: status, cls: 'bg-gray-700 text-gray-400' }
  return (
    <span className={`text-[11px] font-mono px-2 py-0.5 rounded-full whitespace-nowrap ${cfg.cls}`}>
      {cfg.label}
    </span>
  )
}

// ── Painel de análise lateral ─────────────────────────────────────────────────

const TIPO_FUNIL_OPTS: Array<TipoFunil | ''> = ['', 'Quiz', 'Quiz + PV', 'Quiz + VSL', 'VSL', 'PV + VSL', 'PV', 'Checkout']
const FORMATO_OPTS: Array<FormatoEntregavel | ''> = ['', 'educacao', 'ferramenta', 'pack', 'servico', 'comunidade', 'fisico', 'outro']

interface PainelAnaliseProps {
  oferta: Oferta
  onClose: () => void
  onSaved: () => void
}

function PainelAnalise({ oferta, onClose, onSaved }: PainelAnaliseProps) {
  const queryClient = useQueryClient()

  // ── Estado local dos campos editáveis
  const [tipoFunil, setTipoFunil] = useState<TipoFunil | ''>(oferta.tipo_funil ?? '')
  const [formato, setFormato] = useState<FormatoEntregavel | ''>(oferta.formato_entregavel ?? '')
  const [expert, setExpert] = useState<boolean>(oferta.expert ?? false)
  const [infoapp, setInfoapp] = useState<boolean>(oferta.oportunidade_infoapp ?? false)
  const [nicho, setNicho] = useState<string>(oferta.nicho ?? '')
  const [obs, setObs] = useState<string>(oferta.observacoes ?? '')
  const [confirmDialog, setConfirmDialog] = useState<'monitorar' | 'descartar' | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)

  // Re-inicializa quando oferta muda
  useEffect(() => {
    setTipoFunil(oferta.tipo_funil ?? '')
    setFormato(oferta.formato_entregavel ?? '')
    setExpert(oferta.expert ?? false)
    setInfoapp(oferta.oportunidade_infoapp ?? false)
    setNicho(oferta.nicho ?? '')
    setObs(oferta.observacoes ?? '')
    setSaveError(null)
    setConfirmDialog(null)
  }, [oferta.id])

  // ── Mutation: Salvar campos editáveis
  const saveMutation = useMutation({
    mutationFn: () =>
      updateOferta(oferta.id, {
        tipo_funil: tipoFunil || null,
        formato_entregavel: formato || null,
        expert,
        oportunidade_infoapp: infoapp,
        nicho: nicho || null,
        observacoes: obs || null,
        ...(oferta.status === 'alerta' ? { status: 'em_analise_funil' as OfertaStatus } : {}),
      }),
    onSuccess: () => {
      setSaveError(null)
      queryClient.invalidateQueries({ queryKey: ['lt-counts'] })
      queryClient.invalidateQueries({ queryKey: ['lt-gate'] })
      queryClient.invalidateQueries({ queryKey: ['lt-infoapp'] })
      queryClient.invalidateQueries({ queryKey: ['lt-candidatas'] })
      onSaved()
    },
    onError: (err: Error) => {
      setSaveError(err.message ?? 'Erro ao salvar')
    },
  })

  // ── Mutation: Monitorar
  const monitorarMutation = useMutation({
    mutationFn: () =>
      updateOferta(oferta.id, {
        status: 'monitorando',
        data_inicio_monitoramento: new Date().toISOString().split('T')[0],
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['lt-counts'] })
      queryClient.invalidateQueries({ queryKey: ['lt-gate'] })
      queryClient.invalidateQueries({ queryKey: ['lt-tracker'] })
      queryClient.invalidateQueries({ queryKey: ['lt-infoapp'] })
      queryClient.invalidateQueries({ queryKey: ['lt-candidatas'] })
      setConfirmDialog(null)
      onClose()
    },
  })

  // ── Mutation: Descartar
  const descartarMutation = useMutation({
    mutationFn: () =>
      updateOferta(oferta.id, { status: 'descartada' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['lt-counts'] })
      queryClient.invalidateQueries({ queryKey: ['lt-gate'] })
      queryClient.invalidateQueries({ queryKey: ['lt-tracker'] })
      queryClient.invalidateQueries({ queryKey: ['lt-infoapp'] })
      queryClient.invalidateQueries({ queryKey: ['lt-candidatas'] })
      setConfirmDialog(null)
      onClose()
    },
  })

  const saving = saveMutation.isPending
  const acting = monitorarMutation.isPending || descartarMutation.isPending

  // ── Estilos reutilizáveis
  const labelCls = 'text-xs font-mono text-gray-500 mb-1 block'
  const inputCls = 'w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm font-mono text-gray-100 focus:outline-none focus:border-violet-500'

  return (
    <>
      {/* Painel */}
      <div className="w-80 shrink-0 bg-gray-900 border border-gray-800 rounded-xl p-4 flex flex-col gap-3 self-start">
        {/* Header */}
        <div className="flex items-start justify-between gap-2">
          <div className="flex flex-col gap-1 min-w-0">
            <h3 className="text-sm font-mono font-semibold text-gray-100 truncate">
              {oferta.anunciante ?? '—'}
            </h3>
            <div className="flex items-center gap-1.5 flex-wrap">
              <StatusChip status={oferta.status} />
              {oferta.vertical_risco === true && (
                <span className="text-[11px] font-mono px-2 py-0.5 rounded-full bg-red-500/20 text-red-400 border border-red-500/40 whitespace-nowrap">
                  ⚠️ Risco
                </span>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-gray-600 hover:text-gray-300 transition-colors shrink-0 text-lg leading-none"
          >
            ×
          </button>
        </div>

        {/* Seção de enriquecimento — somente leitura */}
        <div className="grid grid-cols-2 gap-x-3 gap-y-2">
          <div>
            <p className="text-xs font-mono text-gray-500">Vertical</p>
            <p className="text-sm font-mono text-gray-300">{oferta.vertical ?? '—'}</p>
          </div>
          <div>
            <p className="text-xs font-mono text-gray-500">Mercado</p>
            <p className="text-sm font-mono text-gray-300">{oferta.mercado ?? '—'}</p>
          </div>
          <div>
            <p className="text-xs font-mono text-gray-500">Preço</p>
            <p className="text-sm font-mono text-gray-300">{oferta.preco_visivel ?? '—'}</p>
          </div>
          <div>
            <p className="text-xs font-mono text-gray-500">Criativos</p>
            <p className="text-sm font-mono text-gray-300">
              {fmtMix(oferta.n_criativos_video, oferta.n_criativos_imagem)}
            </p>
          </div>
        </div>

        <div className="border-t border-gray-800 my-0" />

        {/* Campos editáveis */}
        <div className="flex flex-col gap-3">
          {/* Tipo de Funil */}
          <div>
            <label className={labelCls}>Tipo de Funil</label>
            <select
              value={tipoFunil}
              onChange={e => setTipoFunil(e.target.value as TipoFunil | '')}
              className={inputCls}
            >
              {TIPO_FUNIL_OPTS.map(o => (
                <option key={o} value={o}>{o === '' ? '— selecionar —' : o}</option>
              ))}
            </select>
          </div>

          {/* Formato */}
          <div>
            <label className={labelCls}>Formato</label>
            <select
              value={formato}
              onChange={e => setFormato(e.target.value as FormatoEntregavel | '')}
              className={inputCls}
            >
              {FORMATO_OPTS.map(o => (
                <option key={o} value={o}>{o === '' ? '— selecionar —' : o}</option>
              ))}
            </select>
          </div>

          {/* Toggles */}
          <div className="flex items-center gap-4">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={expert}
                onChange={e => setExpert(e.target.checked)}
                className="accent-violet-500 w-4 h-4"
              />
              <span className="text-sm font-mono text-gray-300">Expert</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={infoapp}
                onChange={e => setInfoapp(e.target.checked)}
                className="accent-amber-400 w-4 h-4"
              />
              <span className="text-sm font-mono text-gray-300">⭐ Infoapp</span>
            </label>
          </div>

          {/* Nicho */}
          <div>
            <label className={labelCls}>Nicho</label>
            <input
              type="text"
              value={nicho}
              onChange={e => setNicho(e.target.value)}
              className={inputCls}
              placeholder="ex: emagrecimento, finanças..."
            />
          </div>

          {/* Observações */}
          <div>
            <label className={labelCls}>Observações</label>
            <textarea
              rows={3}
              value={obs}
              onChange={e => setObs(e.target.value)}
              className={`${inputCls} resize-none`}
              placeholder="Anotações sobre a oferta..."
            />
          </div>

          {/* Erro de salvar */}
          {saveError && (
            <p className="text-red-400 text-xs font-mono">{saveError}</p>
          )}

          {/* Botão Salvar */}
          <button
            onClick={() => saveMutation.mutate()}
            disabled={saving}
            className="bg-violet-600 hover:bg-violet-700 disabled:opacity-60 text-white font-mono text-sm px-4 py-2 rounded-lg transition-colors"
          >
            {saving ? 'Salvando...' : 'Salvar'}
          </button>
        </div>

        <div className="border-t border-gray-800 my-0" />

        {/* Ações finais */}
        <div className="flex flex-col gap-2">
          <button
            onClick={() => setConfirmDialog('monitorar')}
            disabled={oferta.status === 'monitorando' || acting}
            className="bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white font-mono text-sm px-4 py-2 rounded-lg transition-colors"
          >
            Monitorar
          </button>
          <button
            onClick={() => setConfirmDialog('descartar')}
            disabled={acting}
            className="bg-red-700/80 hover:bg-red-700 disabled:opacity-50 text-white font-mono text-sm px-4 py-2 rounded-lg transition-colors"
          >
            Descartar
          </button>
        </div>
      </div>

      {/* Confirm dialog — overlay */}
      {confirmDialog !== null && (
        <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center">
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 w-80 flex flex-col gap-4">
            <p className="text-sm font-mono text-gray-200">
              Confirmar:{' '}
              <span className={confirmDialog === 'monitorar' ? 'text-emerald-400' : 'text-red-400'}>
                {confirmDialog === 'monitorar' ? 'Monitorar' : 'Descartar'}
              </span>{' '}
              esta oferta?
            </p>
            <p className="text-xs font-mono text-gray-500">
              {oferta.anunciante ?? '—'}
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => {
                  if (confirmDialog === 'monitorar') monitorarMutation.mutate()
                  else descartarMutation.mutate()
                }}
                disabled={acting}
                className={`flex-1 font-mono text-sm px-4 py-2 rounded-lg transition-colors disabled:opacity-60 ${
                  confirmDialog === 'monitorar'
                    ? 'bg-emerald-600 hover:bg-emerald-700 text-white'
                    : 'bg-red-700/80 hover:bg-red-700 text-white'
                }`}
              >
                {acting ? 'Aguarde...' : 'Confirmar'}
              </button>
              <button
                onClick={() => setConfirmDialog(null)}
                disabled={acting}
                className="flex-1 bg-gray-800 hover:bg-gray-700 text-gray-300 font-mono text-sm px-4 py-2 rounded-lg transition-colors"
              >
                Cancelar
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

// ── Modal: Oferta Manual (FR-9) ───────────────────────────────────────────────

interface ModalOfertaManualProps {
  onClose: () => void
  onOfertaExistente: (oferta: Oferta) => void
  onOfertaCriada: () => void
}

function ModalOfertaManual({ onClose, onOfertaExistente, onOfertaCriada }: ModalOfertaManualProps) {
  const queryClient = useQueryClient()
  const [pageIdInput, setPageIdInput] = useState('')
  const [anunciante, setAnunciante] = useState('')
  const [nicho, setNicho] = useState('')
  const [obsInput, setObsInput] = useState('')
  const [formError, setFormError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const labelCls = 'text-xs font-mono text-gray-500 mb-1 block'
  const inputCls = 'w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm font-mono text-gray-100 focus:outline-none focus:border-violet-500'

  function extractPageId(raw: string): string {
    const trimmed = raw.trim()
    if (trimmed.includes('view_all_page_id=')) {
      try {
        const qsPart = trimmed.split('?')[1] ?? ''
        const id = new URLSearchParams(qsPart).get('view_all_page_id')
        return id ?? trimmed
      } catch {
        return trimmed
      }
    }
    return trimmed
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setFormError(null)

    const pageId = extractPageId(pageIdInput)
    if (!pageId) {
      setFormError('Page ID é obrigatório.')
      return
    }

    // Validação: page_id deve ser numérico (T-34-04)
    if (!/^\d+$/.test(pageId)) {
      setFormError('Page ID deve conter apenas números.')
      return
    }

    setSubmitting(true)
    try {
      // Dedup: verificar se já existe
      const existente = await fetchOfertaByPageId(pageId)
      if (existente !== null) {
        onClose()
        onOfertaExistente(existente)
        return
      }

      // Prefixar observações com "origem: manual (Board)\n"
      const obsFinal = `origem: manual (Board)\n${obsInput}`.trimEnd()

      await insertOferta({
        page_id: pageId,
        anunciante: anunciante.trim() || null,
        nicho: nicho.trim() || null,
        observacoes: obsFinal,
        status: 'alerta',
        pais: 'MULTI',
        link_ad_library: `https://www.facebook.com/ads/library/?view_all_page_id=${pageId}`,
      } as Parameters<typeof insertOferta>[0])

      queryClient.invalidateQueries({ queryKey: ['lt-counts'] })
      queryClient.invalidateQueries({ queryKey: ['lt-gate'] })
      onOfertaCriada()
      onClose()
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Erro ao inserir oferta'
      setFormError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center px-4">
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 w-full max-w-md flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-mono font-semibold text-gray-100">Adicionar Oferta Manual</h2>
          <button
            onClick={onClose}
            className="text-gray-600 hover:text-gray-300 transition-colors text-lg leading-none"
          >
            ×
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <div>
            <label className={labelCls}>Page ID ou Link *</label>
            <input
              type="text"
              value={pageIdInput}
              onChange={e => setPageIdInput(e.target.value)}
              required
              className={inputCls}
              placeholder="123456789 ou https://facebook.com/ads/library/?view_all_page_id=..."
            />
            <p className="text-xs font-mono text-gray-600 mt-1">
              Cole o link da Biblioteca ou o Page ID diretamente.
            </p>
          </div>

          <div>
            <label className={labelCls}>Anunciante (opcional)</label>
            <input
              type="text"
              value={anunciante}
              onChange={e => setAnunciante(e.target.value)}
              className={inputCls}
              placeholder="Nome do anunciante"
            />
          </div>

          <div>
            <label className={labelCls}>Nicho (opcional)</label>
            <input
              type="text"
              value={nicho}
              onChange={e => setNicho(e.target.value)}
              className={inputCls}
              placeholder="ex: emagrecimento, finanças..."
            />
          </div>

          <div>
            <label className={labelCls}>Observações (opcional)</label>
            <textarea
              rows={3}
              value={obsInput}
              onChange={e => setObsInput(e.target.value)}
              className={`${inputCls} resize-none`}
              placeholder="Anotações adicionais..."
            />
            <p className="text-xs font-mono text-gray-700 mt-1">
              Prefixado automaticamente com "origem: manual (Board)"
            </p>
          </div>

          {formError && (
            <p className="text-red-400 text-xs font-mono">{formError}</p>
          )}

          <div className="flex gap-2 pt-1">
            <button
              type="submit"
              disabled={submitting}
              className="flex-1 bg-violet-600 hover:bg-violet-700 disabled:opacity-60 text-white font-mono text-sm px-4 py-2 rounded-lg transition-colors"
            >
              {submitting ? 'Verificando...' : 'Salvar'}
            </button>
            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              className="flex-1 bg-gray-800 hover:bg-gray-700 text-gray-300 font-mono text-sm px-4 py-2 rounded-lg transition-colors"
            >
              Cancelar
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Toast simples ─────────────────────────────────────────────────────────────

function Toast({ message, onDismiss }: { message: string; onDismiss: () => void }) {
  useEffect(() => {
    const t = setTimeout(onDismiss, 3000)
    return () => clearTimeout(t)
  }, [onDismiss])

  return (
    <div className="fixed top-4 right-4 z-50 bg-amber-500/20 border border-amber-500/40 text-amber-300 font-mono text-sm px-4 py-3 rounded-xl shadow-lg">
      {message}
    </div>
  )
}

// ── Helpers de ordenação (compartilhados) ────────────────────────────────────

function sortRows<T>(rows: T[], key: keyof T, dir: 'asc' | 'desc'): T[] {
  return [...rows].sort((a, b) => {
    const va = a[key], vb = b[key]
    if (va === null || va === undefined) return 1
    if (vb === null || vb === undefined) return -1
    const cmp = va < vb ? -1 : va > vb ? 1 : 0
    return dir === 'asc' ? cmp : -cmp
  })
}

function SortTh({ col, label, active, dir, onSort }: {
  col: string; label: string; active: boolean; dir: 'asc' | 'desc'; onSort: () => void
}) {
  return (
    <th onClick={onSort} className="px-3 py-3 text-left text-xs text-gray-500 uppercase tracking-wider whitespace-nowrap cursor-pointer select-none hover:text-gray-300 transition-colors">
      {label}<span className={`ml-1 ${active ? 'text-violet-400' : 'text-gray-700'}`}>{active ? (dir === 'asc' ? '▲' : '▼') : '⇅'}</span>
    </th>
  )
}

function useSort<K extends string>(def: K, defDir: 'asc' | 'desc' = 'asc') {
  const [key, setKey] = useState<K>(def)
  const [dir, setDir] = useState<'asc' | 'desc'>(defDir)
  const sort = (k: K, numeric?: boolean) => {
    if (key === k) { setDir(d => d === 'asc' ? 'desc' : 'asc') }
    else { setKey(k); setDir(numeric ? 'desc' : 'asc') }
  }
  return { key, dir, sort }
}

// ── Aba Gate ──────────────────────────────────────────────────────────────────

function GateTab() {
  const [filtroMercado, setFiltroMercado] = useState<string>('')
  const [selectedOferta, setSelectedOferta] = useState<Oferta | null>(null)
  const [showManualForm, setShowManualForm] = useState(false)
  const [toastMsg, setToastMsg] = useState<string | null>(null)
  const gs = useSort<'n_anuncios_ativos'|'dias_ativo_oferta'|'nicho'|'mercado'|'preco_visivel'|'formato_entregavel'|'tipo_funil'>('n_anuncios_ativos', 'desc')

  const { data: ofertas, isLoading, error } = useQuery({
    queryKey: ['lt-gate'],
    queryFn: fetchGate,
    staleTime: 30_000,
  })

  // Mercados distintos presentes nos dados
  const mercados = useMemo(() => {
    if (!ofertas) return []
    const set = new Set<string>()
    for (const o of ofertas) {
      if (o.mercado) set.add(o.mercado)
    }
    return Array.from(set).sort()
  }, [ofertas])

  // Filtro + ordenação client-side
  const ofertasFiltradas = useMemo(() => {
    if (!ofertas) return []
    const f = filtroMercado ? ofertas.filter(o => o.mercado === filtroMercado) : ofertas
    return sortRows(f, gs.key as keyof Oferta, gs.dir)
  }, [ofertas, filtroMercado, gs.key, gs.dir])

  // Manter selectedOferta sincronizada com dados atualizados
  const selectedOfertaAtualizada = useMemo(() => {
    if (!selectedOferta || !ofertas) return selectedOferta
    return ofertas.find(o => o.id === selectedOferta.id) ?? selectedOferta
  }, [selectedOferta, ofertas])

  function handleRowClick(o: Oferta) {
    setSelectedOferta(prev => (prev?.id === o.id ? null : o))
  }

  if (isLoading) {
    return <p className="text-gray-600 text-sm font-mono py-12 text-center">Carregando gate...</p>
  }
  if (error) {
    return <p className="text-red-400 text-sm font-mono py-12 text-center">Erro ao carregar gate.</p>
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Barra de ações e filtro */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        {/* Filtro por mercado */}
        <div className="flex items-center gap-2 flex-wrap">
          {mercados.length > 0 && (
            <>
              <span className="text-xs font-mono text-gray-600 mr-1">Mercado:</span>
              <button
                onClick={() => setFiltroMercado('')}
                className={`text-xs font-mono px-3 py-1 rounded-full border transition-colors ${
                  filtroMercado === ''
                    ? 'bg-violet-500/20 text-violet-300 border-violet-500/40'
                    : 'border-gray-700 text-gray-500 hover:text-gray-300 hover:border-gray-600'
                }`}
              >
                Todos
              </button>
              {mercados.map(m => (
                <button
                  key={m}
                  onClick={() => setFiltroMercado(m === filtroMercado ? '' : m)}
                  className={`text-xs font-mono px-3 py-1 rounded-full border transition-colors ${
                    filtroMercado === m
                      ? 'bg-violet-500/20 text-violet-300 border-violet-500/40'
                      : 'border-gray-700 text-gray-500 hover:text-gray-300 hover:border-gray-600'
                  }`}
                >
                  {m}
                </button>
              ))}
            </>
          )}
        </div>

        {/* Botão oferta manual */}
        <button
          onClick={() => setShowManualForm(true)}
          className="text-xs font-mono px-3 py-1.5 rounded-lg border border-violet-500/40 text-violet-400 hover:bg-violet-500/10 transition-colors whitespace-nowrap"
        >
          + Oferta manual
        </button>
      </div>

      {/* Layout: tabela + painel */}
      <div className={selectedOferta ? 'flex gap-4 items-start' : ''}>
        {/* Tabela Gate */}
        <div className={`overflow-x-auto rounded-xl border border-gray-800 ${selectedOferta ? 'flex-1 min-w-0' : ''}`}>
          <table className="w-full text-sm font-mono">
            <thead>
              <tr className="border-b border-gray-800 bg-gray-900/60">
                <th className="px-4 py-3 text-left text-xs text-gray-500 uppercase tracking-wider whitespace-nowrap">Anunciante</th>
                <th className="px-3 py-3 text-left text-xs text-gray-500 uppercase tracking-wider whitespace-nowrap">Mix</th>
                <SortTh col="n_anuncios_ativos"  label="Ativos"   active={gs.key==='n_anuncios_ativos'}  dir={gs.dir} onSort={() => gs.sort('n_anuncios_ativos', true)} />
                <SortTh col="dias_ativo_oferta"  label="Dias"     active={gs.key==='dias_ativo_oferta'}  dir={gs.dir} onSort={() => gs.sort('dias_ativo_oferta', true)} />
                <SortTh col="nicho"              label="Nicho"    active={gs.key==='nicho'}              dir={gs.dir} onSort={() => gs.sort('nicho')} />
                <SortTh col="mercado"            label="Mercado"  active={gs.key==='mercado'}            dir={gs.dir} onSort={() => gs.sort('mercado')} />
                <SortTh col="preco_visivel"      label="Preço"    active={gs.key==='preco_visivel'}      dir={gs.dir} onSort={() => gs.sort('preco_visivel')} />
                <SortTh col="formato_entregavel" label="Formato"  active={gs.key==='formato_entregavel'} dir={gs.dir} onSort={() => gs.sort('formato_entregavel')} />
                <SortTh col="tipo_funil"         label="Funil"    active={gs.key==='tipo_funil'}         dir={gs.dir} onSort={() => gs.sort('tipo_funil')} />
                <th className="px-3 py-3 text-left text-xs text-gray-500 uppercase tracking-wider">Status</th>
                <th className="px-3 py-3 text-left text-xs text-gray-500 uppercase tracking-wider whitespace-nowrap">Atualizado</th>
                <th className="px-3 py-3 text-left text-xs text-gray-500 uppercase tracking-wider">Lib</th>
              </tr>
            </thead>
            <tbody>
              {ofertasFiltradas.length === 0 && (
                <tr>
                  <td colSpan={12} className="px-4 py-12 text-center text-gray-600 text-sm">
                    Nenhuma oferta no Gate
                  </td>
                </tr>
              )}
              {ofertasFiltradas.map((o: Oferta) => {
                const isSelected = selectedOferta?.id === o.id
                return (
                  <tr
                    key={o.id}
                    className={`border-b border-gray-800/60 hover:bg-gray-800/30 transition-colors ${
                      isSelected ? 'bg-violet-500/5 border-l-2 border-l-violet-500' : ''
                    }`}
                  >
                    {/* Anunciante — clicável */}
                    <td className="px-4 py-3 max-w-[160px]">
                      <button
                        onClick={() => handleRowClick(o)}
                        className="text-left text-gray-200 hover:text-violet-300 transition-colors truncate max-w-full flex items-center gap-1.5"
                      >
                        {o.vertical_risco && (
                          <span className="text-red-400 shrink-0" title="Vertical de risco">⚠️</span>
                        )}
                        <span className="truncate">{o.anunciante ?? '—'}</span>
                      </button>
                    </td>

                    {/* Mix criativos */}
                    <td className="px-3 py-3 text-gray-400 whitespace-nowrap">
                      {fmtMix(o.n_criativos_video, o.n_criativos_imagem)}
                    </td>

                    {/* Ativos */}
                    <td className="px-3 py-3 text-gray-300">
                      {o.n_anuncios_ativos ?? '—'}
                    </td>

                    {/* Dias */}
                    <td className="px-3 py-3 text-gray-400">
                      {o.dias_ativo_oferta ?? '—'}
                    </td>

                    {/* Nicho */}
                    <td className="px-3 py-3 text-gray-400 max-w-[120px]">
                      <span className="truncate block">{o.nicho ?? '—'}</span>
                    </td>

                    {/* Mercado */}
                    <td className="px-3 py-3 text-gray-400 whitespace-nowrap">
                      {o.mercado ?? '—'}
                    </td>

                    {/* Preço */}
                    <td className="px-3 py-3 text-gray-400 whitespace-nowrap">
                      {o.preco_visivel ?? '—'}
                    </td>

                    {/* Formato + star infoapp */}
                    <td className="px-3 py-3 text-gray-400 whitespace-nowrap">
                      {o.oportunidade_infoapp && <span className="text-amber-400 mr-1">⭐</span>}
                      {o.formato_entregavel ?? '—'}
                    </td>

                    {/* Funil */}
                    <td className="px-3 py-3 text-gray-400 whitespace-nowrap">
                      {o.tipo_funil ?? '—'}
                    </td>

                    {/* Status chip */}
                    <td className="px-3 py-3">
                      <StatusChip status={o.status} />
                    </td>

                    {/* Atualizado em */}
                    <td className="px-3 py-3 text-gray-600 text-xs whitespace-nowrap">
                      {fmtDate(o.atualizado_em)}
                    </td>

                    {/* Botão biblioteca */}
                    <td className="px-3 py-3">
                      {o.link_ad_library ? (
                        <a
                          href={o.link_ad_library}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-xs font-mono text-violet-400 hover:text-violet-300 border border-violet-500/30 px-2 py-1 rounded transition-colors whitespace-nowrap"
                        >
                          Biblioteca
                        </a>
                      ) : (
                        <span className="text-gray-700 text-xs">—</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {/* Painel lateral */}
        {selectedOfertaAtualizada && (
          <PainelAnalise
            oferta={selectedOfertaAtualizada}
            onClose={() => setSelectedOferta(null)}
            onSaved={() => {
              // onSaved: painel permanece aberto após salvar — só fecha em Monitorar/Descartar
            }}
          />
        )}
      </div>

      <p className="text-xs font-mono text-gray-700">
        {ofertasFiltradas.length} oferta{ofertasFiltradas.length !== 1 ? 's' : ''} no gate
        {filtroMercado ? ` · mercado: ${filtroMercado}` : ''}
      </p>

      {/* Modal oferta manual */}
      {showManualForm && (
        <ModalOfertaManual
          onClose={() => setShowManualForm(false)}
          onOfertaExistente={(oferta) => {
            setSelectedOferta(oferta)
            setToastMsg('Oferta já existe para este page_id')
          }}
          onOfertaCriada={() => {
            setToastMsg(null)
          }}
        />
      )}

      {/* Toast */}
      {toastMsg && (
        <Toast message={toastMsg} onDismiss={() => setToastMsg(null)} />
      )}
    </div>
  )
}

// ── Sparkline SVG inline ──────────────────────────────────────────────────────

function SparklineSVG({ points }: { points: ObservacaoDiaria[] }) {
  if (!points || points.length < 2) return <span className="text-gray-700 text-xs">—</span>
  const vals = points.map(p => p.n_ads_ativos)
  const min = Math.min(...vals)
  const max = Math.max(...vals)
  const W = 80, H = 28, PAD = 2
  const normalize = (v: number) =>
    max === min ? H / 2 : PAD + (H - 2 * PAD) * (1 - (v - min) / (max - min))
  const step = (W - 2 * PAD) / (vals.length - 1)
  const d = vals
    .map((v, i) => `${i === 0 ? 'M' : 'L'}${(PAD + i * step).toFixed(1)},${normalize(v).toFixed(1)}`)
    .join(' ')
  return (
    <svg width={W} height={H} className="overflow-visible">
      <path d={d} fill="none" stroke="#34d399" strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  )
}

// ── Aba Tracker ───────────────────────────────────────────────────────────────

function TrackerTab() {
  const queryClient = useQueryClient()

  const { data: trackerRows, isLoading: loadingTracker, error: errorTracker } = useQuery({
    queryKey: ['lt-tracker'],
    queryFn: fetchTracker,
    staleTime: 30_000,
  })

  const trackerIds = useMemo(() => (trackerRows ?? []).map(r => r.id), [trackerRows])

  const { data: sparklines } = useQuery({
    queryKey: ['lt-sparklines', trackerIds],
    queryFn: () => fetchSparklines(trackerIds),
    enabled: trackerIds.length > 0,
  })

  const overrideMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: OfertaStatus }) =>
      updateOferta(id, { status }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['lt-tracker'] })
      queryClient.invalidateQueries({ queryKey: ['lt-counts'] })
    },
  })

  function handleOverrideStatus(id: string, status: OfertaStatus) {
    overrideMutation.mutate({ id, status })
  }

  const ts = useSort<'nicho'|'tipo_funil'|'data_inicio_monitoramento'|'dia_1'|'dia_atual'|'delta_7d'|'maximo'|'minimo'>('dia_atual', 'desc')
  const trackerOrdenados = useMemo(() => {
    if (!trackerRows) return []
    return sortRows(trackerRows, ts.key as any, ts.dir)
  }, [trackerRows, ts.key, ts.dir])

  if (loadingTracker) {
    return <p className="text-gray-600 font-mono text-sm py-8 text-center">Carregando tracker...</p>
  }
  if (errorTracker) {
    return <p className="text-red-400 font-mono text-sm py-8 text-center">Erro ao carregar tracker.</p>
  }
  if (!trackerRows || trackerRows.length === 0) {
    return <p className="text-gray-600 font-mono text-sm py-8 text-center">Nenhuma oferta em monitoramento.</p>
  }

  function renderDelta7d(val: number | null) {
    if (val === null) return <span className="text-gray-600">—</span>
    if (val > 0) return <span className="text-emerald-400 font-mono">+{val}</span>
    if (val < 0) return <span className="text-red-400 font-mono">{val}</span>
    return <span className="text-gray-500 font-mono">0</span>
  }

  function renderTendencia(val: 'subindo' | 'caindo' | 'estavel' | null) {
    if (val === 'subindo') return '🚀'
    if (val === 'caindo') return '📉'
    if (val === 'estavel') return '➡️'
    return '—'
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-gray-800">
      <table className="w-full text-xs font-mono">
        <thead>
          <tr className="border-b border-gray-800 bg-gray-900/60">
            <th className="text-gray-500 text-left px-3 py-2 font-normal border-b border-gray-800 whitespace-nowrap">Anunciante</th>
            <SortTh col="nicho"                     label="Nicho"    active={ts.key==='nicho'}                     dir={ts.dir} onSort={() => ts.sort('nicho')} />
            <SortTh col="tipo_funil"                label="Funil"    active={ts.key==='tipo_funil'}                dir={ts.dir} onSort={() => ts.sort('tipo_funil')} />
            <th className="text-gray-500 text-left px-3 py-2 font-normal border-b border-gray-800 whitespace-nowrap">Expert</th>
            <SortTh col="data_inicio_monitoramento" label="Início"   active={ts.key==='data_inicio_monitoramento'} dir={ts.dir} onSort={() => ts.sort('data_inicio_monitoramento')} />
            <th className="text-gray-500 text-left px-3 py-2 font-normal border-b border-gray-800 whitespace-nowrap">Status</th>
            <SortTh col="dia_1"    label="Dia 1"    active={ts.key==='dia_1'}    dir={ts.dir} onSort={() => ts.sort('dia_1', true)} />
            <SortTh col="dia_atual" label="Dia atual" active={ts.key==='dia_atual'} dir={ts.dir} onSort={() => ts.sort('dia_atual', true)} />
            <SortTh col="delta_7d" label="Δ7d"      active={ts.key==='delta_7d'} dir={ts.dir} onSort={() => ts.sort('delta_7d', true)} />
            <SortTh col="maximo"   label="Máx"      active={ts.key==='maximo'}   dir={ts.dir} onSort={() => ts.sort('maximo', true)} />
            <SortTh col="minimo"   label="Mín"      active={ts.key==='minimo'}   dir={ts.dir} onSort={() => ts.sort('minimo', true)} />
            <th className="text-gray-500 text-left px-3 py-2 font-normal border-b border-gray-800 whitespace-nowrap">Tendência</th>
            <th className="text-gray-500 text-left px-3 py-2 font-normal border-b border-gray-800 whitespace-nowrap">Sparkline</th>
            <th className="text-gray-500 text-left px-3 py-2 font-normal border-b border-gray-800 whitespace-nowrap">Lib</th>
          </tr>
        </thead>
        <tbody>
          {trackerOrdenados.map(row => (
            <tr key={row.id} className="border-b border-gray-800/40 hover:bg-gray-900/60">
              <td className="px-3 py-2.5 text-gray-300 max-w-[140px]">
                <span className="truncate block">{row.anunciante ?? '—'}</span>
              </td>
              <td className="px-3 py-2.5 text-gray-300 max-w-[120px]">
                <span className="truncate block">{row.nicho ?? '—'}</span>
              </td>
              <td className="px-3 py-2.5 text-gray-300 whitespace-nowrap">
                {row.tipo_funil ?? '—'}
              </td>
              <td className="px-3 py-2.5 whitespace-nowrap">
                {row.expert
                  ? <span className="text-emerald-400">✓</span>
                  : <span className="text-gray-600">—</span>}
              </td>
              <td className="px-3 py-2.5 text-gray-400 whitespace-nowrap">
                {row.data_inicio_monitoramento
                  ? new Date(row.data_inicio_monitoramento).toLocaleDateString('pt-BR')
                  : '—'}
              </td>
              <td className="px-3 py-2.5">
                <select
                  value={row.status}
                  onChange={e => handleOverrideStatus(row.id, e.target.value as OfertaStatus)}
                  className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs font-mono text-gray-300"
                >
                  <option value="monitorando">monitorando</option>
                  <option value="em_escala">em_escala</option>
                  <option value="saturada">saturada</option>
                  <option value="pausada">pausada</option>
                </select>
              </td>
              <td className="px-3 py-2.5 text-gray-400">
                {row.dia_1 ?? '—'}
              </td>
              <td className="px-3 py-2.5 text-gray-400">
                {row.dia_atual ?? '—'}
              </td>
              <td className="px-3 py-2.5">
                {renderDelta7d(row.delta_7d)}
              </td>
              <td className="px-3 py-2.5 text-gray-400">
                {row.maximo ?? '—'}
              </td>
              <td className="px-3 py-2.5 text-gray-400">
                {row.minimo ?? '—'}
              </td>
              <td className="px-3 py-2.5 text-gray-300 text-base">
                {renderTendencia(row.tendencia)}
              </td>
              <td className="px-3 py-2.5">
                <SparklineSVG points={sparklines?.[row.id] ?? []} />
              </td>
              <td className="px-3 py-2.5">
                {row.link_ad_library ? (
                  <a
                    href={row.link_ad_library}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs font-mono text-violet-400 hover:text-violet-300 border border-violet-500/30 px-2 py-1 rounded transition-colors whitespace-nowrap"
                  >
                    Biblioteca
                  </a>
                ) : (
                  <span className="text-gray-700 text-xs">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-xs font-mono text-gray-700 px-3 py-2">
        {trackerRows.length} oferta{trackerRows.length !== 1 ? 's' : ''} em monitoramento
      </p>
    </div>
  )
}

// ── Aba Candidatas (FR-5) ─────────────────────────────────────────────────────

function CandidatasTab() {
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [selectedOferta, setSelectedOferta] = useState<Oferta | null>(null)

  const { data: candidatas, isLoading, error } = useQuery({
    queryKey: ['lt-candidatas'],
    queryFn: fetchCandidatas,
    staleTime: 30_000,
  })

  // Manter selecionada sincronizada com dados atualizados
  const selectedOfertaAtualizada = useMemo(() => {
    if (!selectedOferta || !candidatas) return selectedOferta
    return candidatas.find(o => o.id === selectedOferta.id) ?? selectedOferta
  }, [selectedOferta, candidatas])

  const { data: trackerRows } = useQuery({
    queryKey: ['lt-candidatas-tracker'],
    queryFn: fetchCandidatasTracker,
    staleTime: 30_000,
    enabled: (candidatas?.length ?? 0) > 0,
  })

  const candidataIds = useMemo(
    () => (candidatas ?? []).map(c => c.id),
    [candidatas]
  )

  const { data: sparklines } = useQuery({
    queryKey: ['lt-sparklines-cand', candidataIds],
    queryFn: () => fetchSparklines(candidataIds),
    staleTime: 60_000,
    enabled: candidataIds.length > 0,
  })

  // Join em memória: TrackerRow por id para acessar delta_7d e tendencia
  const trackerById = useMemo(() => {
    const map: Record<string, NonNullable<typeof trackerRows>[number]> = {}
    for (const row of trackerRows ?? []) {
      map[row.id] = row
    }
    return map
  }, [trackerRows])

  const cs = useSort<'nicho'|'tipo_funil'|'formato_entregavel'|'n_anuncios_ativos'|'dias_ativo_oferta'>('n_anuncios_ativos', 'desc')
  const candidatasOrdenadas = useMemo(() => {
    if (!candidatas) return []
    return sortRows(candidatas, cs.key as keyof Oferta, cs.dir)
  }, [candidatas, cs.key, cs.dir])

  function handleCopiarBriefing(oferta: Oferta) {
    const md = [
      `## Briefing — ${oferta.anunciante ?? '(sem nome)'}`,
      ``,
      `- **page_id:** ${oferta.page_id ?? '—'}`,
      `- **Link:** ${oferta.link_ad_library ?? '—'}`,
      `- **Nicho:** ${oferta.nicho ?? '—'}`,
      `- **Funil:** ${oferta.tipo_funil ?? '—'}`,
      `- **Formato:** ${oferta.formato_entregavel ?? '—'}`,
      `- **N. anúncios ativos:** ${oferta.n_anuncios_ativos ?? '—'}`,
      `- **Dias ativo:** ${oferta.dias_ativo_oferta ?? '—'}`,
      `- **Observações:** ${oferta.observacoes ?? '—'}`,
    ].join('\n')

    navigator.clipboard.writeText(md).then(() => {
      setCopiedId(oferta.id)
      setTimeout(() => setCopiedId(null), 2000)
    })
  }

  if (isLoading) {
    return <p className="text-gray-600 text-sm font-mono py-12 text-center">Carregando...</p>
  }
  if (error) {
    return <p className="text-red-400 text-sm font-mono py-12 text-center">Erro ao carregar.</p>
  }
  if (!candidatas || candidatas.length === 0) {
    return <p className="text-gray-600 font-mono text-sm py-8 text-center">Nenhuma candidata ainda.</p>
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Layout: tabela + painel */}
      <div className={selectedOfertaAtualizada ? 'flex gap-4 items-start' : ''}>
      <div className={`overflow-x-auto rounded-xl border border-gray-800 ${selectedOfertaAtualizada ? 'flex-1 min-w-0' : ''}`}>
        <table className="w-full text-sm font-mono">
          <thead>
            <tr className="border-b border-gray-800 bg-gray-900/60">
              <th className="px-4 py-3 text-left text-xs text-gray-500 uppercase tracking-wider whitespace-nowrap">Anunciante</th>
              <SortTh col="nicho"              label="Nicho"    active={cs.key==='nicho'}              dir={cs.dir} onSort={() => cs.sort('nicho')} />
              <SortTh col="tipo_funil"         label="Funil"    active={cs.key==='tipo_funil'}         dir={cs.dir} onSort={() => cs.sort('tipo_funil')} />
              <SortTh col="formato_entregavel" label="Formato"  active={cs.key==='formato_entregavel'} dir={cs.dir} onSort={() => cs.sort('formato_entregavel')} />
              <th className="px-3 py-3 text-left text-xs text-gray-500 uppercase tracking-wider">Expert</th>
              <SortTh col="n_anuncios_ativos"  label="Ativos"   active={cs.key==='n_anuncios_ativos'}  dir={cs.dir} onSort={() => cs.sort('n_anuncios_ativos', true)} />
              <SortTh col="dias_ativo_oferta"  label="Dias"     active={cs.key==='dias_ativo_oferta'}  dir={cs.dir} onSort={() => cs.sort('dias_ativo_oferta', true)} />
              <th className="px-3 py-3 text-left text-xs text-gray-500 uppercase tracking-wider">Δ7d</th>
              <th className="px-3 py-3 text-left text-xs text-gray-500 uppercase tracking-wider">Spark</th>
              <th className="px-3 py-3 text-left text-xs text-gray-500 uppercase tracking-wider whitespace-nowrap">Observações</th>
              <th className="px-3 py-3 text-left text-xs text-gray-500 uppercase tracking-wider">Lib</th>
              <th className="px-3 py-3 text-left text-xs text-gray-500 uppercase tracking-wider">Briefing</th>
            </tr>
          </thead>
          <tbody>
            {candidatasOrdenadas.map((o: Oferta) => {
              const tracker = trackerById[o.id]
              const delta = tracker?.delta_7d ?? null
              const pontos = sparklines?.[o.id] ?? []

              const deltaEl = delta === null ? (
                <span className="text-gray-600">—</span>
              ) : delta > 0 ? (
                <span className="text-emerald-400">+{delta}</span>
              ) : delta < 0 ? (
                <span className="text-red-400">{delta}</span>
              ) : (
                <span className="text-gray-500">0</span>
              )

              const isSelected = selectedOfertaAtualizada?.id === o.id
              return (
                <tr
                  key={o.id}
                  className={`border-b border-gray-800/60 hover:bg-gray-800/30 transition-colors ${
                    isSelected ? 'bg-violet-500/5 border-l-2 border-l-violet-500' : ''
                  }`}
                >
                  <td className="px-4 py-3 max-w-[160px]">
                    <button
                      onClick={() => setSelectedOferta(prev => (prev?.id === o.id ? null : o))}
                      className="flex items-center gap-1.5 text-left w-full hover:text-violet-300 transition-colors"
                    >
                      {o.vertical_risco && <span className="text-red-400 shrink-0" title="Vertical de risco">⚠️</span>}
                      <span className="truncate text-gray-200">{o.anunciante ?? '—'}</span>
                    </button>
                  </td>
                  <td className="px-3 py-3 text-gray-400 max-w-[120px]">
                    <span className="truncate block">{o.nicho ?? '—'}</span>
                  </td>
                  <td className="px-3 py-3 text-gray-400 whitespace-nowrap">{o.tipo_funil ?? '—'}</td>
                  <td className="px-3 py-3 text-gray-400 whitespace-nowrap">
                    {o.oportunidade_infoapp && <span className="text-amber-400 mr-1">⭐</span>}
                    {o.formato_entregavel ?? '—'}
                  </td>
                  <td className="px-3 py-3 text-gray-400">{o.expert ? 'Sim' : '—'}</td>
                  <td className="px-3 py-3 text-gray-300">{o.n_anuncios_ativos ?? '—'}</td>
                  <td className="px-3 py-3 text-gray-400">{o.dias_ativo_oferta ?? '—'}</td>
                  <td className="px-3 py-3 text-xs">{deltaEl}</td>
                  <td className="px-3 py-3">
                    <SparklineSVG points={pontos} />
                  </td>
                  <td className="px-3 py-3 text-gray-500 text-xs max-w-[160px]">
                    <span className="truncate block" title={o.observacoes ?? ''}>
                      {o.observacoes
                        ? o.observacoes.slice(0, 40) + (o.observacoes.length > 40 ? '…' : '')
                        : '—'}
                    </span>
                  </td>
                  <td className="px-3 py-3">
                    {o.link_ad_library ? (
                      <a
                        href={o.link_ad_library}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs font-mono text-violet-400 hover:text-violet-300 border border-violet-500/30 px-2 py-1 rounded transition-colors whitespace-nowrap"
                      >
                        Biblioteca
                      </a>
                    ) : (
                      <span className="text-gray-700 text-xs">—</span>
                    )}
                  </td>
                  <td className="px-3 py-3">
                    {copiedId === o.id ? (
                      <span className="text-emerald-400 text-xs font-mono">Copiado!</span>
                    ) : (
                      <button
                        onClick={() => handleCopiarBriefing(o)}
                        className="text-xs font-mono text-gray-400 hover:text-gray-200 border border-gray-700 hover:border-gray-600 px-2 py-1 rounded transition-colors whitespace-nowrap"
                      >
                        Copiar
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Painel lateral de análise */}
      {selectedOfertaAtualizada && (
        <PainelAnalise
          oferta={selectedOfertaAtualizada}
          onClose={() => setSelectedOferta(null)}
          onSaved={() => {
            // painel permanece aberto após salvar
          }}
        />
      )}
      </div>
      <p className="text-xs font-mono text-gray-700">
        {candidatas.length} candidata{candidatas.length !== 1 ? 's' : ''}
      </p>
    </div>
  )
}

// ── Aba Infoapp (FR-6) ────────────────────────────────────────────────────────

function InfoappTab() {
  const [selectedOferta, setSelectedOferta] = useState<Oferta | null>(null)

  const { data: ofertas, isLoading, error } = useQuery({
    queryKey: ['lt-infoapp'],
    queryFn: fetchInfoapp,
    staleTime: 30_000,
  })

  // Manter selecionada sincronizada com dados atualizados
  const selectedOfertaAtualizada = useMemo(() => {
    if (!selectedOferta || !ofertas) return selectedOferta
    return ofertas.find(o => o.id === selectedOferta.id) ?? selectedOferta
  }, [selectedOferta, ofertas])

  const iis = useSort<'n_anuncios_ativos'|'dias_ativo_oferta'|'nicho'|'mercado'|'preco_visivel'|'formato_entregavel'|'tipo_funil'>('n_anuncios_ativos', 'desc')
  const ofertasOrdenadas = useMemo(() => {
    if (!ofertas) return []
    return sortRows(ofertas, iis.key as keyof Oferta, iis.dir)
  }, [ofertas, iis.key, iis.dir])

  if (isLoading) {
    return <p className="text-gray-600 text-sm font-mono py-12 text-center">Carregando...</p>
  }
  if (error) {
    return <p className="text-red-400 text-sm font-mono py-12 text-center">Erro ao carregar.</p>
  }
  if (!ofertas || ofertas.length === 0) {
    return <p className="text-gray-600 font-mono text-sm py-8 text-center">Nenhuma oferta infoapp no momento.</p>
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Layout: tabela + painel */}
      <div className={selectedOfertaAtualizada ? 'flex gap-4 items-start' : ''}>
      <div className={`overflow-x-auto rounded-xl border border-gray-800 ${selectedOfertaAtualizada ? 'flex-1 min-w-0' : ''}`}>
        <table className="w-full text-sm font-mono">
          <thead>
            <tr className="border-b border-gray-800 bg-gray-900/60">
              <th className="px-4 py-3 text-left text-xs text-gray-500 uppercase tracking-wider whitespace-nowrap">Anunciante</th>
              <th className="px-3 py-3 text-left text-xs text-gray-500 uppercase tracking-wider whitespace-nowrap">Mix</th>
              <SortTh col="n_anuncios_ativos"  label="Ativos"   active={iis.key==='n_anuncios_ativos'}  dir={iis.dir} onSort={() => iis.sort('n_anuncios_ativos', true)} />
              <SortTh col="dias_ativo_oferta"  label="Dias"     active={iis.key==='dias_ativo_oferta'}  dir={iis.dir} onSort={() => iis.sort('dias_ativo_oferta', true)} />
              <SortTh col="nicho"              label="Nicho"    active={iis.key==='nicho'}              dir={iis.dir} onSort={() => iis.sort('nicho')} />
              <SortTh col="mercado"            label="Mercado"  active={iis.key==='mercado'}            dir={iis.dir} onSort={() => iis.sort('mercado')} />
              <SortTh col="preco_visivel"      label="Preço"    active={iis.key==='preco_visivel'}      dir={iis.dir} onSort={() => iis.sort('preco_visivel')} />
              <SortTh col="formato_entregavel" label="Formato"  active={iis.key==='formato_entregavel'} dir={iis.dir} onSort={() => iis.sort('formato_entregavel')} />
              <SortTh col="tipo_funil"         label="Funil"    active={iis.key==='tipo_funil'}         dir={iis.dir} onSort={() => iis.sort('tipo_funil')} />
              <th className="px-3 py-3 text-left text-xs text-gray-500 uppercase tracking-wider">Status</th>
              <th className="px-3 py-3 text-left text-xs text-gray-500 uppercase tracking-wider whitespace-nowrap">Atualizado</th>
              <th className="px-3 py-3 text-left text-xs text-gray-500 uppercase tracking-wider">Lib</th>
            </tr>
          </thead>
          <tbody>
            {ofertasOrdenadas.map((o: Oferta) => {
              const isSelected = selectedOfertaAtualizada?.id === o.id
              return (
              <tr
                key={o.id}
                className={`border-b border-gray-800/60 hover:bg-gray-800/30 transition-colors ${
                  isSelected ? 'bg-violet-500/5 border-l-2 border-l-violet-500' : ''
                }`}
              >
                <td className="px-4 py-3 max-w-[160px]">
                  <button
                    onClick={() => setSelectedOferta(prev => (prev?.id === o.id ? null : o))}
                    className="flex items-center gap-1.5 text-left w-full hover:text-violet-300 transition-colors"
                  >
                    {o.vertical_risco && <span className="text-red-400 shrink-0" title="Vertical de risco">⚠️</span>}
                    <span className="truncate text-gray-200">{o.anunciante ?? '—'}</span>
                  </button>
                </td>
                <td className="px-3 py-3 text-gray-400 whitespace-nowrap">
                  {fmtMix(o.n_criativos_video, o.n_criativos_imagem)}
                </td>
                <td className="px-3 py-3 text-gray-300">{o.n_anuncios_ativos ?? '—'}</td>
                <td className="px-3 py-3 text-gray-400">{o.dias_ativo_oferta ?? '—'}</td>
                <td className="px-3 py-3 text-gray-400 max-w-[120px]">
                  <span className="truncate block">{o.nicho ?? '—'}</span>
                </td>
                <td className="px-3 py-3 text-gray-400 whitespace-nowrap">{o.mercado ?? '—'}</td>
                <td className="px-3 py-3 text-gray-400 whitespace-nowrap">{o.preco_visivel ?? '—'}</td>
                <td className="px-3 py-3 text-gray-400 whitespace-nowrap">
                  <span className="text-amber-400 mr-1">⭐</span>
                  {o.formato_entregavel ?? '—'}
                </td>
                <td className="px-3 py-3 text-gray-400 whitespace-nowrap">{o.tipo_funil ?? '—'}</td>
                <td className="px-3 py-3">
                  <StatusChip status={o.status} />
                </td>
                <td className="px-3 py-3 text-gray-600 text-xs whitespace-nowrap">
                  {fmtDate(o.atualizado_em)}
                </td>
                <td className="px-3 py-3">
                  {o.link_ad_library ? (
                    <a
                      href={o.link_ad_library}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs font-mono text-violet-400 hover:text-violet-300 border border-violet-500/30 px-2 py-1 rounded transition-colors whitespace-nowrap"
                    >
                      Biblioteca
                    </a>
                  ) : (
                    <span className="text-gray-700 text-xs">—</span>
                  )}
                </td>
              </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Painel lateral de análise */}
      {selectedOfertaAtualizada && (
        <PainelAnalise
          oferta={selectedOfertaAtualizada}
          onClose={() => setSelectedOferta(null)}
          onSaved={() => {
            // painel permanece aberto após salvar
          }}
        />
      )}
      </div>
      <p className="text-xs font-mono text-gray-700">
        {ofertas.length} oferta{ofertas.length !== 1 ? 's' : ''} infoapp
      </p>
    </div>
  )
}

// ── Aba Arquivo (FR-7) ────────────────────────────────────────────────────────

const ARQUIVO_STATUS_OPTS: Array<{ value: OfertaStatus | ''; label: string }> = [
  { value: '', label: 'Todos' },
  { value: 'descartada', label: 'Descartada' },
  { value: 'saturada', label: 'Saturada' },
  { value: 'pausada', label: 'Pausada' },
]

function ArquivoTab() {
  const [arquivoBusca, setArquivoBusca] = useState('')
  const [arquivoBuscaDebounced, setArquivoBuscaDebounced] = useState('')
  const [arquivoStatus, setArquivoStatus] = useState<OfertaStatus | ''>('')

  // Debounce 300ms para não disparar query a cada tecla
  useEffect(() => {
    const t = setTimeout(() => setArquivoBuscaDebounced(arquivoBusca), 300)
    return () => clearTimeout(t)
  }, [arquivoBusca])

  const { data: ofertas, isLoading, error } = useQuery({
    queryKey: ['lt-arquivo', arquivoStatus, arquivoBuscaDebounced],
    queryFn: () => fetchArquivo({
      status: arquivoStatus || undefined,
      busca: arquivoBuscaDebounced || undefined,
    }),
    staleTime: 30_000,
  })

  const arqs = useSort<'nicho'|'tipo_funil'|'formato_entregavel'|'n_anuncios_ativos'|'dias_ativo_oferta'>('dias_ativo_oferta', 'desc')
  const ofertasOrdenadas = useMemo(() => {
    if (!ofertas) return []
    return sortRows(ofertas, arqs.key as keyof Oferta, arqs.dir)
  }, [ofertas, arqs.key, arqs.dir])

  return (
    <div className="flex flex-col gap-3">
      {/* Header: busca + filtros de status */}
      <div className="flex items-center gap-3 flex-wrap">
        <input
          type="text"
          placeholder="Buscar anunciante..."
          value={arquivoBusca}
          onChange={e => setArquivoBusca(e.target.value)}
          className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm font-mono text-gray-100 focus:outline-none focus:border-violet-500 w-56"
        />
        <div className="flex items-center gap-2 flex-wrap">
          {ARQUIVO_STATUS_OPTS.map(opt => (
            <button
              key={opt.value}
              onClick={() => setArquivoStatus(opt.value)}
              className={`text-xs font-mono px-3 py-1 rounded-full border transition-colors ${
                arquivoStatus === opt.value
                  ? 'bg-violet-500/20 text-violet-300 border-violet-500/40'
                  : 'border-gray-700 text-gray-500 hover:text-gray-300 hover:border-gray-600'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tabela — somente leitura */}
      {isLoading ? (
        <p className="text-gray-600 text-sm font-mono py-12 text-center">Carregando...</p>
      ) : error ? (
        <p className="text-red-400 text-sm font-mono py-12 text-center">Erro ao carregar.</p>
      ) : !ofertas || ofertas.length === 0 ? (
        <p className="text-gray-600 font-mono text-sm py-8 text-center">Nenhuma oferta no arquivo.</p>
      ) : (
        <>
          <div className="overflow-x-auto rounded-xl border border-gray-800">
            <table className="w-full text-sm font-mono">
              <thead>
                <tr className="border-b border-gray-800 bg-gray-900/60">
                  <th className="px-4 py-3 text-left text-xs text-gray-500 uppercase tracking-wider whitespace-nowrap">Anunciante</th>
                  <SortTh col="nicho"              label="Nicho"    active={arqs.key==='nicho'}              dir={arqs.dir} onSort={() => arqs.sort('nicho')} />
                  <SortTh col="tipo_funil"         label="Funil"    active={arqs.key==='tipo_funil'}         dir={arqs.dir} onSort={() => arqs.sort('tipo_funil')} />
                  <SortTh col="formato_entregavel" label="Formato"  active={arqs.key==='formato_entregavel'} dir={arqs.dir} onSort={() => arqs.sort('formato_entregavel')} />
                  <SortTh col="n_anuncios_ativos"  label="Ativos"   active={arqs.key==='n_anuncios_ativos'}  dir={arqs.dir} onSort={() => arqs.sort('n_anuncios_ativos', true)} />
                  <SortTh col="dias_ativo_oferta"  label="Dias"     active={arqs.key==='dias_ativo_oferta'}  dir={arqs.dir} onSort={() => arqs.sort('dias_ativo_oferta', true)} />
                  <th className="px-3 py-3 text-left text-xs text-gray-500 uppercase tracking-wider">Status</th>
                  <th className="px-3 py-3 text-left text-xs text-gray-500 uppercase tracking-wider whitespace-nowrap">Atualizado</th>
                  <th className="px-3 py-3 text-left text-xs text-gray-500 uppercase tracking-wider">Lib</th>
                </tr>
              </thead>
              <tbody>
                {ofertasOrdenadas.map((o: Oferta) => (
                  <tr key={o.id} className="border-b border-gray-800/60 hover:bg-gray-800/30 transition-colors">
                    <td className="px-4 py-3 max-w-[160px]">
                      <span className="truncate block text-gray-300">{o.anunciante ?? '—'}</span>
                    </td>
                    <td className="px-3 py-3 text-gray-400 max-w-[120px]">
                      <span className="truncate block">{o.nicho ?? '—'}</span>
                    </td>
                    <td className="px-3 py-3 text-gray-400 whitespace-nowrap">{o.tipo_funil ?? '—'}</td>
                    <td className="px-3 py-3 text-gray-400 whitespace-nowrap">
                      {o.oportunidade_infoapp && <span className="text-amber-400 mr-1">⭐</span>}
                      {o.formato_entregavel ?? '—'}
                    </td>
                    <td className="px-3 py-3 text-gray-400">{o.n_anuncios_ativos ?? '—'}</td>
                    <td className="px-3 py-3 text-gray-400">{o.dias_ativo_oferta ?? '—'}</td>
                    <td className="px-3 py-3">
                      <StatusChip status={o.status} />
                    </td>
                    <td className="px-3 py-3 text-gray-600 text-xs whitespace-nowrap">
                      {fmtDate(o.atualizado_em)}
                    </td>
                    <td className="px-3 py-3">
                      {o.link_ad_library ? (
                        <a
                          href={o.link_ad_library}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-xs font-mono text-violet-400 hover:text-violet-300 border border-violet-500/30 px-2 py-1 rounded transition-colors whitespace-nowrap"
                        >
                          Biblioteca
                        </a>
                      ) : (
                        <span className="text-gray-700 text-xs">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs font-mono text-gray-700">
            {ofertas.length} oferta{ofertas.length !== 1 ? 's' : ''} no arquivo
            {arquivoStatus ? ` · ${arquivoStatus}` : ''}
            {arquivoBuscaDebounced ? ` · busca: "${arquivoBuscaDebounced}"` : ''}
          </p>
        </>
      )}
    </div>
  )
}

// ── Aba Rastros (FR-10) ───────────────────────────────────────────────────────

const RASTRO_GRUPO_OPTS: RastroGrupo[] = ['builder', 'checkout', 'resposta_direta', 'nicho', 'formato']
const RASTRO_TIPO_BUSCA_OPTS: Array<'plataforma' | 'nicho' | 'formato'> = ['plataforma', 'nicho', 'formato']

const RASTRO_STATUS_CFG: Record<RastroStatus, { label: string; cls: string }> = {
  a_testar:    { label: 'a_testar',    cls: 'bg-amber-500/20 text-amber-400 border border-amber-500/40' },
  testado:     { label: 'testado',     cls: 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40' },
  sem_retorno: { label: 'sem_retorno', cls: 'bg-gray-700/20 text-gray-500 border border-gray-700/30' },
}

// Estado local de edição por linha
interface RastroEditState {
  grupo: RastroGrupo
  tipo_busca: 'plataforma' | 'nicho' | 'formato'
  nicho: string
  funil_hint: string
  populacao_observada: string // string para input controlado, converte para number no save
}

function RastrosTab() {
  const queryClient = useQueryClient()

  // Form de inserção
  const [showForm, setShowForm] = useState(false)
  const [formQuery, setFormQuery] = useState('')
  const [formGrupo, setFormGrupo] = useState<RastroGrupo | ''>('')
  const [formTipoBusca, setFormTipoBusca] = useState<'plataforma' | 'nicho' | 'formato'>('plataforma')
  const [formNicho, setFormNicho] = useState('')
  const [formFunilHint, setFormFunilHint] = useState('')
  const [formErr, setFormErr] = useState<string | null>(null)

  // Estado de edição inline por linha (rastroId → estado editado)
  const [editState, setEditState] = useState<Record<string, RastroEditState>>({})

  // Query principal
  const { data: rastros, isLoading: loadingRastros, error: errorRastros } = useQuery({
    queryKey: ['lt-rastros'],
    queryFn: fetchRastros,
    enabled: true,
  })

  const rrs = useSort<'grupo'|'tipo_busca'|'nicho'|'populacao_observada'|'criado_em'>('criado_em', 'desc')
  const rastrosOrdenados = useMemo(() => {
    if (!rastros) return []
    return sortRows(rastros, rrs.key as any, rrs.dir)
  }, [rastros, rrs.key, rrs.dir])

  // Inicializa o editState quando rastros carregam (sem sobrescrever edições ativas)
  useEffect(() => {
    if (!rastros) return
    setEditState(prev => {
      const next: Record<string, RastroEditState> = { ...prev }
      for (const r of rastros) {
        if (!(r.id in next)) {
          next[r.id] = {
            grupo: r.grupo,
            tipo_busca: r.tipo_busca,
            nicho: r.nicho ?? '',
            funil_hint: r.funil_hint ?? '',
            populacao_observada: r.populacao_observada != null ? String(r.populacao_observada) : '',
          }
        }
      }
      return next
    })
  }, [rastros])

  // Mutation: atualizar rastro
  const rastroMutation = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Parameters<typeof updateRastro>[1] }) =>
      updateRastro(id, patch),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['lt-rastros'] }),
  })

  function handleUpdateRastro(id: string, patch: Parameters<typeof updateRastro>[1]) {
    rastroMutation.mutate({ id, patch })
  }

  // Mutation: inserir rastro
  const insertMutation = useMutation({
    mutationFn: insertRastro,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['lt-rastros'] })
      queryClient.invalidateQueries({ queryKey: ['lt-rastros-count'] })
      setShowForm(false)
      setFormQuery('')
      setFormGrupo('')
      setFormNicho('')
      setFormFunilHint('')
      setFormTipoBusca('plataforma')
      setFormErr(null)
    },
    onError: (e: Error) => setFormErr(e.message),
  })

  function handleSubmitForm(ev: React.FormEvent) {
    ev.preventDefault()
    setFormErr(null)
    if (!formQuery.trim()) {
      setFormErr('Query é obrigatória.')
      return
    }
    if (!formGrupo) {
      setFormErr('Grupo é obrigatório.')
      return
    }
    insertMutation.mutate({
      query: formQuery.trim(),
      grupo: formGrupo,
      tipo_busca: formTipoBusca,
      nicho: formNicho.trim() || null,
      funil_hint: formFunilHint.trim() || null,
    })
  }

  // Verificar se há rastros de nicho (aviso global)
  const temNicho = (rastros ?? []).some(r => r.tipo_busca === 'nicho')

  const labelCls = 'text-xs font-mono text-gray-500 mb-1 block'
  const inputCls = 'w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm font-mono text-gray-100 focus:outline-none focus:border-violet-500'
  const inlineInputCls = 'bg-transparent border-b border-gray-700 text-xs font-mono text-gray-300 focus:border-violet-500 outline-none w-full'
  const inlineSelectCls = 'bg-gray-900 border border-gray-700 rounded px-1 py-0.5 text-xs font-mono text-gray-300 focus:border-violet-500 outline-none'

  if (loadingRastros) {
    return <p className="text-gray-600 font-mono text-sm py-8 text-center">Carregando rastros...</p>
  }
  if (errorRastros) {
    return <p className="text-red-400 font-mono text-sm py-8 text-center">Erro ao carregar rastros.</p>
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-sm font-mono font-semibold text-gray-100">Catálogo de Rastros</h2>
          {temNicho && (
            <p className="text-xs font-mono text-gray-600 mt-1">
              plataforma roda no Flow 1 (domingo) · nicho e formato rodam no Flow 3 (seg/qua/sex)
            </p>
          )}
        </div>
        <button
          onClick={() => setShowForm(true)}
          className="text-xs font-mono px-3 py-1.5 rounded-lg border border-violet-500/40 text-violet-400 hover:bg-violet-500/10 transition-colors whitespace-nowrap"
        >
          + Novo Rastro
        </button>
      </div>

      {/* Modal: Novo Rastro */}
      {showForm && (
        <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center px-4">
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 w-full max-w-md flex flex-col gap-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-mono font-semibold text-gray-100">Novo Rastro</h3>
              <button
                onClick={() => { setShowForm(false); setFormErr(null) }}
                className="text-gray-600 hover:text-gray-300 transition-colors text-lg leading-none"
              >
                ×
              </button>
            </div>

            <form onSubmit={handleSubmitForm} className="flex flex-col gap-3">
              <div>
                <label className={labelCls}>Query (única) *</label>
                <input
                  type="text"
                  value={formQuery}
                  onChange={e => setFormQuery(e.target.value)}
                  required
                  className={inputCls}
                  placeholder='ex: "quiz saúde mãe"'
                />
              </div>

              <div>
                <label className={labelCls}>Grupo *</label>
                <select
                  value={formGrupo}
                  onChange={e => setFormGrupo(e.target.value as RastroGrupo | '')}
                  required
                  className={inputCls}
                >
                  <option value="">— selecionar —</option>
                  {RASTRO_GRUPO_OPTS.map(g => (
                    <option key={g} value={g}>{g}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className={labelCls}>Tipo de Busca *</label>
                <select
                  value={formTipoBusca}
                  onChange={e => setFormTipoBusca(e.target.value as 'plataforma' | 'nicho' | 'formato')}
                  className={inputCls}
                >
                  {RASTRO_TIPO_BUSCA_OPTS.map(t => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className={labelCls}>Nicho (opcional — só para tipo nicho)</label>
                <input
                  type="text"
                  value={formNicho}
                  onChange={e => setFormNicho(e.target.value)}
                  className={inputCls}
                  placeholder="ex: Emagrecimento"
                />
              </div>

              <div>
                <label className={labelCls}>Hint de Funil (opcional)</label>
                <input
                  type="text"
                  value={formFunilHint}
                  onChange={e => setFormFunilHint(e.target.value)}
                  className={inputCls}
                  placeholder="ex: Quiz"
                />
              </div>

              {formErr && (
                <p className="text-amber-400 text-xs font-mono mt-1">{formErr}</p>
              )}

              <div className="flex gap-2 pt-1">
                <button
                  type="submit"
                  disabled={insertMutation.isPending}
                  className="flex-1 bg-violet-600 hover:bg-violet-700 disabled:opacity-60 text-white font-mono text-sm px-4 py-2 rounded-lg transition-colors"
                >
                  {insertMutation.isPending ? 'Inserindo...' : 'Adicionar'}
                </button>
                <button
                  type="button"
                  onClick={() => { setShowForm(false); setFormErr(null) }}
                  disabled={insertMutation.isPending}
                  className="flex-1 bg-gray-800 hover:bg-gray-700 text-gray-300 font-mono text-sm px-4 py-2 rounded-lg transition-colors"
                >
                  Cancelar
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Tabela */}
      {(!rastros || rastros.length === 0) ? (
        <p className="text-gray-600 font-mono text-sm py-8 text-center">Nenhum rastro cadastrado ainda.</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-gray-800">
          <table className="w-full text-xs font-mono">
            <thead>
              <tr className="border-b border-gray-800 bg-gray-900/60">
                <th className="text-gray-500 text-left px-3 py-2 font-normal whitespace-nowrap">Query</th>
                <SortTh col="grupo"                label="Grupo"       active={rrs.key==='grupo'}                dir={rrs.dir} onSort={() => rrs.sort('grupo')} />
                <SortTh col="tipo_busca"           label="Tipo Busca"  active={rrs.key==='tipo_busca'}           dir={rrs.dir} onSort={() => rrs.sort('tipo_busca')} />
                <SortTh col="nicho"                label="Nicho"       active={rrs.key==='nicho'}                dir={rrs.dir} onSort={() => rrs.sort('nicho')} />
                <th className="text-gray-500 text-left px-3 py-2 font-normal whitespace-nowrap">Funil Hint</th>
                <SortTh col="populacao_observada"  label="Pop. obs."   active={rrs.key==='populacao_observada'}  dir={rrs.dir} onSort={() => rrs.sort('populacao_observada', true)} />
                <th className="text-gray-500 text-left px-3 py-2 font-normal whitespace-nowrap">Status</th>
                <SortTh col="criado_em"            label="Criado em"   active={rrs.key==='criado_em'}            dir={rrs.dir} onSort={() => rrs.sort('criado_em')} />
                <th className="text-gray-500 text-left px-3 py-2 font-normal whitespace-nowrap">Ações</th>
              </tr>
            </thead>
            <tbody>
              {rastrosOrdenados.map((r: Rastro) => {
                const es = editState[r.id]
                const isSemRetorno = r.status === 'sem_retorno'
                const statusCfg = RASTRO_STATUS_CFG[r.status] ?? RASTRO_STATUS_CFG.a_testar

                return (
                  <tr
                    key={r.id}
                    className={`border-b border-gray-800/40 hover:bg-gray-900/50 ${isSemRetorno ? 'opacity-60' : ''}`}
                  >
                    {/* Query — somente leitura, imutável */}
                    <td className="px-3 py-2.5 max-w-[200px]">
                      <span className={`font-mono text-gray-200 truncate block ${isSemRetorno ? 'line-through' : ''}`}>
                        {r.query}
                      </span>
                    </td>

                    {/* Grupo — dropdown inline */}
                    <td className="px-3 py-2.5">
                      {es ? (
                        <select
                          value={es.grupo}
                          onChange={e => {
                            const novoGrupo = e.target.value as RastroGrupo
                            setEditState(prev => ({ ...prev, [r.id]: { ...prev[r.id], grupo: novoGrupo } }))
                            handleUpdateRastro(r.id, { grupo: novoGrupo })
                          }}
                          className={inlineSelectCls}
                        >
                          {RASTRO_GRUPO_OPTS.map(g => (
                            <option key={g} value={g}>{g}</option>
                          ))}
                        </select>
                      ) : (
                        <span className="text-gray-400">{r.grupo}</span>
                      )}
                    </td>

                    {/* Tipo de Busca — dropdown inline com badge de aviso */}
                    <td className="px-3 py-2.5 whitespace-nowrap">
                      {es ? (
                        <div className="flex items-center gap-1 flex-wrap">
                          <select
                            value={es.tipo_busca}
                            onChange={e => {
                              const novoTipo = e.target.value as 'plataforma' | 'nicho' | 'formato'
                              setEditState(prev => ({ ...prev, [r.id]: { ...prev[r.id], tipo_busca: novoTipo } }))
                              handleUpdateRastro(r.id, { tipo_busca: novoTipo })
                            }}
                            className={inlineSelectCls}
                          >
                            {RASTRO_TIPO_BUSCA_OPTS.map(t => (
                              <option key={t} value={t}>{t}</option>
                            ))}
                          </select>

                        </div>
                      ) : (
                        <div className="flex items-center gap-1">
                          <span className="text-gray-400">{r.tipo_busca}</span>

                        </div>
                      )}
                    </td>

                    {/* Nicho — input inline com onBlur */}
                    <td className="px-3 py-2.5">
                      {es ? (
                        <input
                          type="text"
                          value={es.nicho}
                          onChange={e => setEditState(prev => ({ ...prev, [r.id]: { ...prev[r.id], nicho: e.target.value } }))}
                          onBlur={() => {
                            const novoNicho = es.nicho.trim() || null
                            const nichoAtual = r.nicho ?? null
                            if (novoNicho !== nichoAtual) {
                              handleUpdateRastro(r.id, { nicho: novoNicho })
                            }
                          }}
                          className={`${inlineInputCls} w-28`}
                          placeholder="—"
                        />
                      ) : (
                        <span className="text-gray-400">{r.nicho ?? '—'}</span>
                      )}
                    </td>

                    {/* Funil Hint — input inline com onBlur */}
                    <td className="px-3 py-2.5">
                      {es ? (
                        <input
                          type="text"
                          value={es.funil_hint}
                          onChange={e => setEditState(prev => ({ ...prev, [r.id]: { ...prev[r.id], funil_hint: e.target.value } }))}
                          onBlur={() => {
                            const novoHint = es.funil_hint.trim() || null
                            const hintAtual = r.funil_hint ?? null
                            if (novoHint !== hintAtual) {
                              handleUpdateRastro(r.id, { funil_hint: novoHint })
                            }
                          }}
                          className={`${inlineInputCls} w-24`}
                          placeholder="—"
                        />
                      ) : (
                        <span className="text-gray-500">{r.funil_hint ?? '—'}</span>
                      )}
                    </td>

                    {/* Pop. Observada — input numérico inline com onBlur */}
                    <td className="px-3 py-2.5">
                      {es ? (
                        <input
                          type="number"
                          value={es.populacao_observada}
                          onChange={e => setEditState(prev => ({ ...prev, [r.id]: { ...prev[r.id], populacao_observada: e.target.value } }))}
                          onBlur={() => {
                            const novoVal = es.populacao_observada.trim() !== ''
                              ? parseInt(es.populacao_observada, 10)
                              : null
                            const valAtual = r.populacao_observada ?? null
                            if (novoVal !== valAtual) {
                              handleUpdateRastro(r.id, { populacao_observada: novoVal })
                            }
                          }}
                          className={`${inlineInputCls} w-16`}
                          placeholder="—"
                        />
                      ) : (
                        <span className="text-gray-500">{r.populacao_observada ?? '—'}</span>
                      )}
                    </td>

                    {/* Status — badge colorido */}
                    <td className="px-3 py-2.5">
                      <span className={`text-[11px] font-mono px-2 py-0.5 rounded-full whitespace-nowrap ${statusCfg.cls}`}>
                        {statusCfg.label}
                      </span>
                    </td>

                    {/* Criado em */}
                    <td className="px-3 py-2.5 text-gray-600 whitespace-nowrap">
                      {fmtDate(r.criado_em)}
                    </td>

                    {/* Ações — toggle Pausar/Reativar; SEM botão de excluir */}
                    <td className="px-3 py-2.5 whitespace-nowrap">
                      {isSemRetorno ? (
                        <button
                          onClick={() => handleUpdateRastro(r.id, { status: 'a_testar' })}
                          disabled={rastroMutation.isPending}
                          className="text-[10px] px-2 py-0.5 rounded border border-emerald-500/40 text-emerald-400 hover:bg-emerald-500/10 transition-colors disabled:opacity-50 whitespace-nowrap"
                        >
                          Reativar
                        </button>
                      ) : (
                        <button
                          onClick={() => handleUpdateRastro(r.id, { status: 'sem_retorno' })}
                          disabled={rastroMutation.isPending}
                          className="text-[10px] px-2 py-0.5 rounded border border-gray-600/40 text-gray-400 hover:bg-gray-700/20 transition-colors disabled:opacity-50 whitespace-nowrap"
                        >
                          Pausar
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <p className="text-xs font-mono text-gray-700 px-3 py-2">
            {rastros.length} rastro{rastros.length !== 1 ? 's' : ''}
          </p>
        </div>
      )}
    </div>
  )
}

// ── Página principal ──────────────────────────────────────────────────────────

export function LowTicket() {
  const [aba, setAba] = useState<Aba>('gate')

  const { data: counts, isLoading: loadingCounts } = useQuery({
    queryKey: ['lt-counts'],
    queryFn: fetchOfertasCounts,
    staleTime: 60_000,
  })

  const { data: atualizadoEm } = useQuery({
    queryKey: ['lt-atualizado-em'],
    queryFn: fetchAtualizadoEm,
    staleTime: 60_000,
  })

  const { data: rastrosCount } = useQuery({
    queryKey: ['lt-rastros-count'],
    queryFn: fetchRastrosCount,
    staleTime: 60_000,
  })

  // Tiles do header
  type TileKey = {
    key: Aba
    label: string
    status?: keyof typeof STATUS_CFG | 'arquivo' | 'infoapp'
    cls: string
  }

  const TILES: TileKey[] = [
    { key: 'gate',       label: 'Gate',        cls: 'text-amber-400' },
    { key: 'tracker',    label: 'Monitorando', cls: 'text-emerald-400' },
    { key: 'candidatas', label: 'Candidatas',  cls: 'text-violet-400' },
    { key: 'infoapp',    label: '⭐ Infoapp',  cls: 'text-amber-300' },
    { key: 'arquivo',    label: 'Arquivo',     cls: 'text-gray-500' },
    { key: 'rastros',    label: 'Rastros',     cls: 'text-gray-400' },
  ]

  function getTileCount(key: Aba): number {
    if (!counts) return 0
    switch (key) {
      case 'gate':       return (counts.alerta ?? 0) + (counts.em_analise_funil ?? 0)
      case 'tracker':    return (counts.monitorando ?? 0) + (counts.em_escala ?? 0)
      case 'candidatas': return counts.candidata ?? 0
      case 'infoapp':    return counts.infoapp ?? 0
      case 'arquivo':    return counts.arquivo ?? 0
      case 'rastros':    return rastrosCount ?? 0
    }
  }

  // Tabs config
  const TABS: { key: Aba; label: string }[] = [
    { key: 'gate',       label: 'Gate' },
    { key: 'tracker',    label: 'Tracker' },
    { key: 'candidatas', label: 'Candidatas' },
    { key: 'infoapp',   label: 'Infoapp' },
    { key: 'arquivo',   label: 'Arquivo' },
    { key: 'rastros',   label: 'Rastros' },
  ]

  return (
    <div className="min-h-screen bg-gray-950">
      {/* Header */}
      <header className="border-b border-gray-800 px-6 py-5 bg-gray-900/40">
        <div className="max-w-7xl mx-auto">
          <div className="flex items-baseline gap-3 mb-1">
            <h1 className="font-mono font-semibold tracking-tight text-gray-100">
              Tracker de Ofertas
            </h1>
            <span className="text-xs font-mono text-gray-600">LowTicket</span>
          </div>
          <p className="text-xs text-gray-600 font-mono">
            Mineração de ofertas de alto volume
            {atualizadoEm
              ? ` · atualizado ${new Date(atualizadoEm).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })}`
              : ''}
          </p>

          {/* Tiles de contagem */}
          <div className="flex gap-3 mt-4 flex-wrap">
            {TILES.map(t => (
              <button
                key={t.key}
                onClick={() => setAba(t.key)}
                className={`bg-gray-900 border rounded-xl px-4 py-3 text-left transition-colors min-w-[100px] ${
                  aba === t.key
                    ? 'border-violet-500/40 bg-violet-500/5'
                    : 'border-gray-800 hover:border-gray-700'
                }`}
              >
                <p className="text-xs font-mono text-gray-500 uppercase tracking-wider">{t.label}</p>
                {loadingCounts ? (
                  <p className="font-mono font-bold text-xl mt-1 text-gray-700">—</p>
                ) : (
                  <p className={`font-mono font-bold text-xl mt-1 ${t.cls}`}>
                    {getTileCount(t.key)}
                  </p>
                )}
              </button>
            ))}
          </div>
        </div>
      </header>

      {/* Conteúdo */}
      <main className="max-w-7xl mx-auto px-6 py-6 flex flex-col gap-4">
        {/* Tabs strip */}
        <div className="flex gap-1 border-b border-gray-800 -mx-1 px-1">
          {TABS.map(t => (
            <button
              key={t.key}
              onClick={() => setAba(t.key)}
              className={`px-4 py-2.5 text-sm font-mono transition-colors rounded-t-lg -mb-px border-b-2 ${
                aba === t.key
                  ? 'text-violet-400 border-violet-500 bg-violet-500/5'
                  : 'text-gray-500 border-transparent hover:text-gray-300 hover:border-gray-700'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Aba ativa */}
        {aba === 'gate'       && <GateTab />}
        {aba === 'tracker'    && <TrackerTab />}
        {aba === 'candidatas' && <CandidatasTab />}
        {aba === 'infoapp'    && <InfoappTab />}
        {aba === 'arquivo'    && <ArquivoTab />}
        {aba === 'rastros'    && <RastrosTab />}
      </main>
    </div>
  )
}
