import { useState, useMemo, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  fetchOfertasCounts,
  fetchGate,
  fetchAtualizadoEm,
  fetchOfertaByPageId,
  fetchTracker,
  fetchSparklines,
  fetchCandidatas,
  fetchCandidatasTracker,
  fetchInfoapp,
  fetchArquivo,
  updateOferta,
  insertOferta,
  type Oferta,
  type OfertaStatus,
  type TipoFunil,
  type FormatoEntregavel,
  type ObservacaoDiaria,
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

const TIPO_FUNIL_OPTS: Array<TipoFunil | ''> = ['', 'Quiz', 'Quiz + PV', 'Quiz + VSL', 'VSL', 'PV + VSL', 'PV']
const FORMATO_OPTS: Array<FormatoEntregavel | ''> = ['', 'educacao', 'ferramenta', 'servico', 'comunidade', 'fisico', 'outro']

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

// ── Aba Gate ──────────────────────────────────────────────────────────────────

function GateTab() {
  const [filtroMercado, setFiltroMercado] = useState<string>('')
  const [selectedOferta, setSelectedOferta] = useState<Oferta | null>(null)
  const [showManualForm, setShowManualForm] = useState(false)
  const [toastMsg, setToastMsg] = useState<string | null>(null)

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

  // Filtro client-side
  const ofertasFiltradas = useMemo(() => {
    if (!ofertas) return []
    if (!filtroMercado) return ofertas
    return ofertas.filter(o => o.mercado === filtroMercado)
  }, [ofertas, filtroMercado])

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
                <th className="px-3 py-3 text-left text-xs text-gray-500 uppercase tracking-wider">Ativos</th>
                <th className="px-3 py-3 text-left text-xs text-gray-500 uppercase tracking-wider">Dias</th>
                <th className="px-3 py-3 text-left text-xs text-gray-500 uppercase tracking-wider">Nicho</th>
                <th className="px-3 py-3 text-left text-xs text-gray-500 uppercase tracking-wider">Mercado</th>
                <th className="px-3 py-3 text-left text-xs text-gray-500 uppercase tracking-wider">Preço</th>
                <th className="px-3 py-3 text-left text-xs text-gray-500 uppercase tracking-wider">Formato</th>
                <th className="px-3 py-3 text-left text-xs text-gray-500 uppercase tracking-wider">Funil</th>
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
            <th className="text-gray-500 text-left px-3 py-2 font-normal border-b border-gray-800 whitespace-nowrap">Nicho</th>
            <th className="text-gray-500 text-left px-3 py-2 font-normal border-b border-gray-800 whitespace-nowrap">Funil</th>
            <th className="text-gray-500 text-left px-3 py-2 font-normal border-b border-gray-800 whitespace-nowrap">Expert</th>
            <th className="text-gray-500 text-left px-3 py-2 font-normal border-b border-gray-800 whitespace-nowrap">Início</th>
            <th className="text-gray-500 text-left px-3 py-2 font-normal border-b border-gray-800 whitespace-nowrap">Status</th>
            <th className="text-gray-500 text-left px-3 py-2 font-normal border-b border-gray-800 whitespace-nowrap">Dia 1</th>
            <th className="text-gray-500 text-left px-3 py-2 font-normal border-b border-gray-800 whitespace-nowrap">Dia atual</th>
            <th className="text-gray-500 text-left px-3 py-2 font-normal border-b border-gray-800 whitespace-nowrap">Δ7d</th>
            <th className="text-gray-500 text-left px-3 py-2 font-normal border-b border-gray-800 whitespace-nowrap">Máx</th>
            <th className="text-gray-500 text-left px-3 py-2 font-normal border-b border-gray-800 whitespace-nowrap">Mín</th>
            <th className="text-gray-500 text-left px-3 py-2 font-normal border-b border-gray-800 whitespace-nowrap">Tendência</th>
            <th className="text-gray-500 text-left px-3 py-2 font-normal border-b border-gray-800 whitespace-nowrap">Sparkline</th>
            <th className="text-gray-500 text-left px-3 py-2 font-normal border-b border-gray-800 whitespace-nowrap">Lib</th>
          </tr>
        </thead>
        <tbody>
          {trackerRows.map(row => (
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

// ── Placeholder para abas futuras ─────────────────────────────────────────────

function EmBreve() {
  return (
    <p className="text-gray-600 font-mono text-sm py-12 text-center">Em breve</p>
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
      case 'rastros':    return 0
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
        {aba === 'candidatas' && <EmBreve />}
        {aba === 'infoapp'    && <EmBreve />}
        {aba === 'arquivo'    && <EmBreve />}
        {aba === 'rastros'    && <EmBreve />}
      </main>
    </div>
  )
}
