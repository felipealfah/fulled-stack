import { createClient } from '@supabase/supabase-js'

// ── Supabase client (projeto LowTicket — separado do Supabase CRM) ──────────
const SUPABASE_URL = import.meta.env.VITE_LOWTICKET_SUPABASE_URL as string
const SUPABASE_PB_KEY = import.meta.env.VITE_LOWTICKET_SUPABASE_PB_KEY as string

export const supabaseLT = createClient(SUPABASE_URL, SUPABASE_PB_KEY)

// ── Enums / tipos ─────────────────────────────────────────────────────────────

export type OfertaStatus =
  | 'novo'
  | 'alerta'
  | 'em_analise_funil'
  | 'descartada'
  | 'monitorando'
  | 'em_escala'
  | 'saturada'
  | 'pausada'
  | 'candidata'

export type TipoFunil = 'Quiz' | 'Quiz + PV' | 'Quiz + VSL' | 'VSL' | 'PV + VSL' | 'PV' | 'Checkout'

export type FormatoEntregavel =
  | 'educacao'
  | 'ferramenta'
  | 'pack'
  | 'servico'
  | 'comunidade'
  | 'fisico'
  | 'outro'

export type RastroGrupo = 'builder' | 'checkout' | 'resposta_direta' | 'nicho' | 'formato'

export type RastroStatus = 'a_testar' | 'testado' | 'sem_retorno'

// ── Interfaces ────────────────────────────────────────────────────────────────

export interface Oferta {
  id: string
  page_id: string | null
  anunciante: string | null
  link_ad_library: string | null
  pais: string | null
  nicho: string | null
  tipo_funil: TipoFunil | null
  formato_entregavel: FormatoEntregavel | null
  oportunidade_infoapp: boolean | null
  expert: boolean | null
  observacoes: string | null
  status: OfertaStatus
  n_anuncios_ativos: number | null
  dias_ativo_oferta: number | null
  data_primeiro_anuncio_ativo: string | null
  data_inicio_monitoramento: string | null
  candidata_raiox: boolean | null
  atualizado_em: string | null
  // Enriquecimento — Flow 4, podem ser null até o agente rodar
  vertical: string | null
  vertical_risco: boolean | null
  preco_visivel: string | null
  mercado: string | null
  n_criativos_video: number | null
  n_criativos_imagem: number | null
}

export interface TrackerRow {
  id: string
  anunciante: string | null
  link_ad_library: string | null
  nicho: string | null
  tipo_funil: TipoFunil | null
  formato_entregavel: FormatoEntregavel | null
  oportunidade_infoapp: boolean | null
  expert: boolean | null
  observacoes: string | null
  data_inicio_monitoramento: string | null
  status: OfertaStatus
  dia_1: number | null
  dia_atual: number | null
  delta_7d: number | null
  maximo: number | null
  minimo: number | null
  tendencia: 'subindo' | 'caindo' | 'estavel' | null
}

export interface ObservacaoDiaria {
  oferta_id: string
  data: string
  dia_monitoramento: number
  n_ads_ativos: number
}

export interface Rastro {
  id: string
  query: string
  grupo: RastroGrupo
  tipo_busca: 'plataforma' | 'nicho' | 'formato'
  funil_hint: string | null
  populacao_observada: number | null
  status: RastroStatus
  criado_em: string
}

// ── Tipo para contagens do header ─────────────────────────────────────────────

export type OfertasCounts = Record<OfertaStatus, number> & {
  infoapp: number
  arquivo: number
}

// ── Helpers de query ──────────────────────────────────────────────────────────

/**
 * Retorna contagens por status + infoapp + arquivo (descartada+saturada+pausada).
 */
export async function fetchOfertasCounts(): Promise<OfertasCounts> {
  // Buscar contagens por status
  const { data: statusRows, error: statusErr } = await supabaseLT
    .from('ofertas')
    .select('status')

  if (statusErr) throw statusErr

  // Inicializar contagens zeradas
  const counts: OfertasCounts = {
    novo: 0,
    alerta: 0,
    em_analise_funil: 0,
    descartada: 0,
    monitorando: 0,
    em_escala: 0,
    saturada: 0,
    pausada: 0,
    candidata: 0,
    infoapp: 0,
    arquivo: 0,
  }

  // Acumular contagens por status
  for (const row of statusRows ?? []) {
    const s = row.status as OfertaStatus
    if (s in counts) {
      counts[s] = (counts[s] ?? 0) + 1
    }
  }

  // Arquivo = descartada + saturada + pausada
  counts.arquivo = counts.descartada + counts.saturada + counts.pausada

  // Contar infoapp (exceto descartadas)
  const { count: infoappCount, error: infoappErr } = await supabaseLT
    .from('ofertas')
    .select('*', { count: 'exact', head: true })
    .eq('oportunidade_infoapp', true)
    .neq('status', 'descartada')

  if (infoappErr) throw infoappErr

  counts.infoapp = infoappCount ?? 0

  return counts
}

/**
 * Retorna ofertas no Gate: status IN ('alerta', 'em_analise_funil'),
 * ordenadas por n_anuncios_ativos DESC NULLS LAST.
 */
export async function fetchGate(): Promise<Oferta[]> {
  const { data, error } = await supabaseLT
    .from('ofertas')
    .select('*')
    .in('status', ['alerta', 'em_analise_funil'])
    .order('n_anuncios_ativos', { ascending: false, nullsFirst: false })

  if (error) throw error
  return (data ?? []) as Oferta[]
}

/**
 * Retorna o MAX(atualizado_em) da tabela ofertas.
 */
export async function fetchAtualizadoEm(): Promise<string | null> {
  const { data, error } = await supabaseLT
    .from('ofertas')
    .select('atualizado_em')
    .order('atualizado_em', { ascending: false })
    .limit(1)
    .single()

  if (error) {
    if (error.code === 'PGRST116') return null // nenhuma linha
    throw error
  }
  return data?.atualizado_em ?? null
}

/**
 * Atualiza campos de uma oferta e seta atualizado_em = now().
 */
export async function updateOferta(id: string, patch: Partial<Oferta>): Promise<void> {
  const { error } = await supabaseLT
    .from('ofertas')
    .update({ ...patch, atualizado_em: new Date().toISOString() })
    .eq('id', id)

  if (error) throw error
}

/**
 * Insere uma nova oferta. Requer page_id + campos opcionais.
 */
export async function insertOferta(
  fields: Pick<Oferta, 'page_id'> & Partial<Oferta>
): Promise<Oferta> {
  const { data, error } = await supabaseLT
    .from('ofertas')
    .insert(fields)
    .select()
    .single()

  if (error) throw error
  return data as Oferta
}

/**
 * Busca uma oferta por page_id. Retorna null se não encontrar.
 * Usado para dedup no FR-9 (oferta manual).
 */
export async function fetchOfertaByPageId(pageId: string): Promise<Oferta | null> {
  const { data, error } = await supabaseLT
    .from('ofertas')
    .select('*')
    .eq('page_id', pageId)
    .limit(1)
    .maybeSingle()

  if (error) throw error
  return data as Oferta | null
}

/**
 * Retorna ofertas em monitoramento via v_tracker.
 * Filtra status IN ('monitorando','em_escala','saturada','pausada'), ordenado por data_inicio_monitoramento DESC.
 */
export async function fetchTracker(): Promise<TrackerRow[]> {
  const { data, error } = await supabaseLT
    .from('v_tracker')
    .select('*')
    .in('status', ['monitorando', 'em_escala', 'saturada', 'pausada'])
    .order('data_inicio_monitoramento', { ascending: false })

  if (error) throw error
  return (data ?? []) as TrackerRow[]
}

/**
 * Retorna candidatas (status = 'candidata') ordenadas por atualizado_em DESC.
 */
export async function fetchCandidatas(): Promise<Oferta[]> {
  const { data, error } = await supabaseLT
    .from('ofertas')
    .select('*')
    .eq('status', 'candidata')
    .order('atualizado_em', { ascending: false })

  if (error) throw error
  return (data ?? []) as Oferta[]
}

/**
 * Retorna rows do v_tracker com status = 'candidata' para join de delta_7d.
 */
export async function fetchCandidatasTracker(): Promise<TrackerRow[]> {
  const { data, error } = await supabaseLT
    .from('v_tracker')
    .select('*')
    .eq('status', 'candidata')
    .order('data_inicio_monitoramento', { ascending: false })

  if (error) throw error
  return (data ?? []) as TrackerRow[]
}

/**
 * Retorna ofertas com oportunidade_infoapp=true exceto descartadas,
 * ordenadas por atualizado_em DESC.
 */
export async function fetchInfoapp(): Promise<Oferta[]> {
  const { data, error } = await supabaseLT
    .from('ofertas')
    .select('*')
    .eq('oportunidade_infoapp', true)
    .neq('status', 'descartada')
    .order('atualizado_em', { ascending: false })

  if (error) throw error
  return (data ?? []) as Oferta[]
}

/**
 * Retorna ofertas arquivadas: status IN (descartada, saturada, pausada).
 * Filtros opcionais: status específico e busca por anunciante (ILIKE).
 * Limite de 200 registros por padrão (T-34-08).
 */
export async function fetchArquivo(params?: {
  status?: OfertaStatus
  busca?: string
}): Promise<Oferta[]> {
  let query = supabaseLT
    .from('ofertas')
    .select('*')
    .in('status', ['descartada', 'saturada', 'pausada'])

  if (params?.status) {
    query = query.eq('status', params.status)
  }

  if (params?.busca && params.busca.trim() !== '') {
    query = query.ilike('anunciante', `%${params.busca}%`)
  }

  const { data, error } = await query
    .order('atualizado_em', { ascending: false })
    .limit(200) // mitigação T-34-08

  if (error) throw error
  return (data ?? []) as Oferta[]
}

/**
 * Retorna observacoes_diarias agrupadas por oferta_id.
 * Limita a 200 IDs para evitar URLs longas no PostgREST (T-34-06).
 */
export async function fetchSparklines(
  ofertaIds: string[]
): Promise<Record<string, ObservacaoDiaria[]>> {
  if (ofertaIds.length === 0) return {}

  // Mitigação T-34-06: limite de 200 IDs
  const ids = ofertaIds.slice(0, 200)

  const { data, error } = await supabaseLT
    .from('observacoes_diarias')
    .select('oferta_id, data, dia_monitoramento, n_ads_ativos')
    .in('oferta_id', ids)
    .order('dia_monitoramento', { ascending: true })

  if (error) throw error

  const result: Record<string, ObservacaoDiaria[]> = {}
  for (const row of data ?? []) {
    const r = row as ObservacaoDiaria
    if (!result[r.oferta_id]) result[r.oferta_id] = []
    result[r.oferta_id].push(r)
  }
  return result
}

// ── Helpers de Rastros (FR-10) ────────────────────────────────────────────────

/**
 * Retorna a contagem total de rastros (todos os status) para o card do header.
 */
export async function fetchRastrosCount(): Promise<number> {
  const { count, error } = await supabaseLT
    .from('rastros')
    .select('*', { count: 'exact', head: true })

  if (error) throw error
  return count ?? 0
}

/**
 * Retorna todos os rastros ordenados por criado_em DESC.
 * Doutrina: nenhum método .delete() é usado neste módulo para rastros.
 */
export async function fetchRastros(): Promise<Rastro[]> {
  const { data, error } = await supabaseLT
    .from('rastros')
    .select('*')
    .order('criado_em', { ascending: false })

  if (error) throw error
  return (data ?? []) as Rastro[]
}

/**
 * Insere um novo rastro com status='a_testar'.
 * Lança erro específico se query já existe (unique constraint 23505).
 * Retorna o rastro inserido.
 */
export async function insertRastro(
  fields: { query: string; grupo: RastroGrupo; tipo_busca: 'plataforma' | 'nicho' | 'formato'; funil_hint?: string | null }
): Promise<Rastro> {
  const { data, error } = await supabaseLT
    .from('rastros')
    .insert({ ...fields, status: 'a_testar' })
    .select()
    .single()

  if (error) {
    if (error.code === '23505') {
      throw new Error('Rastro com esta query já existe')
    }
    throw error
  }
  return data as Rastro
}

/**
 * Atualiza campos permitidos de um rastro. O campo `query` é imutável pós-criação.
 * Nunca chama .delete() — "excluir" = updateRastro(id, { status: 'sem_retorno' }).
 */
export async function updateRastro(
  id: string,
  patch: Partial<Pick<Rastro, 'grupo' | 'tipo_busca' | 'funil_hint' | 'populacao_observada' | 'status'>>
): Promise<void> {
  const { error } = await supabaseLT
    .from('rastros')
    .update(patch)
    .eq('id', id)

  if (error) throw error
}
