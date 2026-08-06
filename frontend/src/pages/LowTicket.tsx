import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  fetchOfertasCounts,
  fetchGate,
  fetchAtualizadoEm,
  type Oferta,
  type OfertaStatus,
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

// ── Aba Gate ──────────────────────────────────────────────────────────────────

function GateTab() {
  const [filtroMercado, setFiltroMercado] = useState<string>('')

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

  if (isLoading) {
    return <p className="text-gray-600 text-sm font-mono py-12 text-center">Carregando gate...</p>
  }
  if (error) {
    return <p className="text-red-400 text-sm font-mono py-12 text-center">Erro ao carregar gate.</p>
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Filtro por mercado */}
      {mercados.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
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
        </div>
      )}

      {/* Tabela Gate */}
      <div className="overflow-x-auto rounded-xl border border-gray-800">
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
            {ofertasFiltradas.map((o: Oferta) => (
              <tr
                key={o.id}
                className="border-b border-gray-800/60 hover:bg-gray-800/30 transition-colors"
              >
                {/* Anunciante — clicável (painel de análise no Plan 02) */}
                <td className="px-4 py-3 max-w-[160px]">
                  <button
                    onClick={() => console.log(o.id)}
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
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-xs font-mono text-gray-700">
        {ofertasFiltradas.length} oferta{ofertasFiltradas.length !== 1 ? 's' : ''} no gate
        {filtroMercado ? ` · mercado: ${filtroMercado}` : ''}
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
        {aba === 'tracker'    && <EmBreve />}
        {aba === 'candidatas' && <EmBreve />}
        {aba === 'infoapp'    && <EmBreve />}
        {aba === 'arquivo'    && <EmBreve />}
        {aba === 'rastros'    && <EmBreve />}
      </main>
    </div>
  )
}
