import axios from 'axios'

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? '/api',
})

// ── Auth: injeta Bearer token e redireciona para /login em 401 ──
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('fulled_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error?.response?.status
    const isLoginCall = error?.config?.url?.includes('/auth/login')
    if (status === 401 && !isLoginCall && window.location.pathname !== '/login') {
      localStorage.removeItem('fulled_token')
      localStorage.removeItem('fulled_user')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

export interface Pesquisa {
  id: string
  projeto_nome: string
  nicho: string
  cidade: string
  status: 'pending_review' | 'approved' | 'rejected' | 'classificado' | 'aprovado'
  created_at: string
  reviewed_at: string | null
  total_keywords?: number
  projeto_id: string | null
  papel: 'principal' | 'servico' | null
  servico_slug: string | null
  kw_principal_id?: number | null
  kw_principal_locked_at?: string | null
}

export interface Keyword {
  id: number
  pesquisa_id: string
  keyword: string
  avg_monthly_searches: number | null
  competition: string | null
  competition_index: number | null
  bid_pos5_8_brl: number | null
  bid_pos1_4_brl: number | null
  score: number | null
  go_nogo: 'GO' | 'NO-GO' | null
  status: 'pending' | 'approved' | 'rejected'
  board_note: string | null
  kw_type: 'principal' | 'silo' | 'geo' | 'descarta' | 'PAGINA_PRINCIPAL' | 'SERVICO' | 'PAGINA_GEO' | 'SECAO' | 'DESCARTA' | null
  competitive_score: number | null
  difficulty_label: string | null
  top_competitor_url: string | null
}

export interface PesquisaDetail {
  pesquisa: Pesquisa
  keywords: Keyword[]
  total: number
  go_count: number
}

export type ProjetoTipo = 'rank_rent' | 'infoproduto' | 'youtube_faceless' | 'facebook_faceless' | 'prospeccao'

export type ProjetoStatus =
  | 'rascunho' | 'ativo' | 'pausado' | 'encerrado'
  | 'research' | 'gate1' | 'gate2' | 'publicado'

export interface ProjetoMetadata {
  // rank_rent
  nicho?: string
  cidade?: string
  site_url?: string
  // infoproduto
  produto?: string
  plataforma?: string
  // youtube_faceless
  canal?: string
  idioma?: string
  // facebook_faceless
  pagina?: string
  formato?: string
  // prospeccao usa nicho + cidade (mesmos campos do rank_rent)
}

export interface Projeto {
  id: string
  projeto_nome: string
  tipo: ProjetoTipo
  status: ProjetoStatus
  receita_mensal: number | null
  metadata: ProjetoMetadata
  pesquisa_id_atual: string | null
  created_at: string
  updated_at: string
  // legacy compat — podem ser null em novos projetos
  nicho: string | null
  cidade: string | null

}

export interface ProjetoDetail extends Projeto {
  pesquisas: Pesquisa[]
}

export interface ProjetoCreate {
  projeto_nome: string
  tipo: ProjetoTipo
  metadata: ProjetoMetadata
  receita_mensal?: number | null
}

export const pesquisasApi = {
  list: () => api.get<Pesquisa[]>('/pesquisas/').then(r => r.data),
  get: (id: string) => api.get<PesquisaDetail>(`/pesquisas/${id}`).then(r => r.data),
  approve: (id: string, approved_keywords: string[]) =>
    api.post(`/pesquisas/${id}/approve`, { approved_keywords }).then(r => r.data),
  reject: (id: string) =>
    api.post(`/pesquisas/${id}/reject`).then(r => r.data),
  updateKeyword: (pesquisaId: string, kwId: number, data: Partial<Keyword>) =>
    api.patch(`/pesquisas/${pesquisaId}/keywords/${kwId}`, data).then(r => r.data),
  deleteKeyword: (pesquisaId: string, kwId: number) =>
    api.delete(`/pesquisas/${pesquisaId}/keywords/${kwId}`).then(r => r.data),
  deletePesquisa: (id: string) =>
    api.delete(`/pesquisas/${id}`).then(r => r.data),
  approveGate2: (id: string, opts?: { projeto_id?: string; criar_projeto?: boolean }) =>
    api.post(`/pesquisas/${id}/approve-gate2`, opts ?? {}).then(r => r.data),
  listGate2Pending: () =>
    api.get<Pesquisa[]>('/pesquisas/').then(r => r.data)
      .then(list => list.filter((p: Pesquisa) => p.status === 'classificado')),
  listGate2: () =>
    api.get<Pesquisa[]>('/pesquisas/').then(r => r.data)
      .then(list => list.filter((p: Pesquisa) =>
        p.status === 'classificado' || p.status === 'aprovado'
      )),
  vincular: (id: string, data: { projeto_id?: string; papel?: string; servico_slug?: string }) =>
    api.patch(`/pesquisas/${id}/vincular`, data).then(r => r.data),
  desvincular: (id: string) =>
    api.delete(`/pesquisas/${id}/vincular`).then(r => r.data),
}

export const projetosApi = {
  list: (tipo?: ProjetoTipo) =>
    api.get<Projeto[]>('/projetos/', { params: tipo ? { tipo } : undefined }).then(r => r.data),
  listByStatus: (status: string) =>
    api.get<Projeto[]>('/projetos/', { params: { status } }).then(r => r.data),
  get: (id: string) =>
    api.get<ProjetoDetail>(`/projetos/${id}`).then(r => r.data),
  create: (data: ProjetoCreate) =>
    api.post<Projeto>('/projetos/', data).then(r => r.data),
  update: (id: string, data: Partial<Omit<Projeto, 'id' | 'created_at'>>) =>
    api.patch<Projeto>(`/projetos/${id}`, data).then(r => r.data),
  delete: (id: string) =>
    api.delete(`/projetos/${id}`).then(r => r.data),
}

// ── Prospecção (leads outbound — Full_AIOS_PROSPECTOR) ───────────────────

export type LeadProspeccaoStatus =
  | 'novo' | 'descartado' | 'redesenhado' | 'publicado'
  | 'proposta_enviada' | 'negociacao' | 'fechado' | 'perdido' | 'inquilino_potencial'

export interface LeadProspeccao {
  id: string
  projeto_id: string | null
  nome: string
  slug: string
  nicho: string
  cidade: string
  nota: number | null
  n_avaliacoes: number | null
  telefone: string | null
  email: string | null
  site_url: string | null
  motivo_site_ruim: string | null
  url_preview: string | null
  status: LeadProspeccaoStatus
  motivo_descarte: string | null
  notas: string | null
  proposta_em: string | null
  // Financeiro / contrato / follow-up
  valor_fechado: number | null
  manutencao_mensal: number | null
  pago: boolean
  contrato_status: 'enviado' | 'assinado' | null
  contrato_em: string | null
  followup_em: string | null
  respondeu_em: string | null
  resumo_resposta: string | null
  doc_cliente: string | null
  end_cliente: string | null
  created_at: string
  updated_at: string
}

export type LeadProspeccaoUpdate = Partial<Pick<LeadProspeccao,
  'status' | 'url_preview' | 'notas' | 'email' | 'telefone' |
  'valor_fechado' | 'manutencao_mensal' | 'pago' | 'contrato_status' |
  'followup_em' | 'respondeu_em' | 'resumo_resposta' | 'doc_cliente' | 'end_cliente'>>

export interface ProspeccaoFinanceiro {
  fechados: number
  receita_fechada: number
  mrr: number
  a_receber: number
  contratos_enviados: number
  contratos_assinados: number
}

export const prospeccaoApi = {
  listLeads: (params?: { projeto_id?: string; status?: string; nicho?: string; cidade?: string }) =>
    api.get<LeadProspeccao[]>('/prospeccao/leads', { params }).then(r => r.data),
  updateLead: (slug: string, data: LeadProspeccaoUpdate) =>
    api.patch<LeadProspeccao>(`/prospeccao/leads/${slug}`, data).then(r => r.data),
  deleteLead: (slug: string) =>
    api.delete(`/prospeccao/leads/${slug}`),
  resumo: (projeto_id?: string) =>
    api.get<Record<string, number>>('/prospeccao/resumo', { params: projeto_id ? { projeto_id } : undefined }).then(r => r.data),
  financeiro: (projeto_id?: string) =>
    api.get<ProspeccaoFinanceiro>('/prospeccao/financeiro', { params: projeto_id ? { projeto_id } : undefined }).then(r => r.data),
}

// ── Financeiro consolidado ────────────────────────────────────────────────

export interface FinanceiroProjeto {
  id: string
  projeto_nome: string
  tipo: ProjetoTipo
  status: string
  receita_mensal: number
}

export interface FinanceiroResumo {
  mrr_total: number
  mrr_projetos: number
  mrr_prospeccao: number
  projetos: FinanceiroProjeto[]
  prospeccao: ProspeccaoFinanceiro & {
    manutencoes: { nome: string; slug: string; cidade: string; manutencao_mensal: number; pago: boolean; projeto_id: string | null }[]
  }
}

export const financeiroApi = {
  resumo: () => api.get<FinanceiroResumo>('/financeiro').then(r => r.data),
}

// ── Ranking ──────────────────────────────────────────────────────────────

export interface RankingRow {
  keyword: string
  kw_type: string | null
  papel: 'principal' | 'servico' | null
  target_url: string | null
  serp_position: number | null
  serp_date: string | null
  sc_impressions_30d: number | null
  sc_clicks_30d: number | null
  sc_ctr_30d: number | null
  sc_position_avg_30d: number | null
  sc_matched_query: string | null
  status: 'RANKEANDO' | 'GAP' | 'SURPRESA' | 'BLOQUEADO'
  serp_position_prev: number | null
  serp_position_delta: number | null
  avg_monthly_searches: number | null
  cpc_brl: number | null
  receita_potencial: number | null
  days_to_index: number | null
}

export interface RankingOverride {
  id: number
  keyword: string
  action: 'promote' | 'block'
  kw_type: string | null
  created_at: string
}

export interface RankingResponse {
  status: 'ok' | 'not_ready'
  projeto_id?: string
  projeto_nome?: string
  dominio?: string
  total?: number
  keywords?: RankingRow[]
  message?: string
  updated_at?: string
}

// ── Ranking History ──────────────────────────────────────────────────────────

export interface RankingHistoryPoint {
  date: string
  serp_position: number | null
  sc_position: number | null
}

export interface RankingKeywordHistory {
  keyword: string
  series: RankingHistoryPoint[]
}

export interface RankingHistoryResponse {
  status: 'ok' | 'not_ready'
  projeto_id?: string
  keywords?: RankingKeywordHistory[]
  message?: string
}

export const rankingApi = {
  get: (projetoId: string) =>
    api.get<RankingResponse>(`/projetos/${projetoId}/ranking`).then(r => r.data),
  refresh: (projetoId: string) =>
    api.post<{ status: string; message: string }>(`/projetos/${projetoId}/rank-intel`).then(r => r.data),
  listOverrides: (projetoId: string) =>
    api.get<RankingOverride[]>(`/projetos/${projetoId}/ranking/overrides`).then(r => r.data),
  upsertOverride: (projetoId: string, keyword: string, action: 'promote' | 'block', kw_type?: string) =>
    api.post(`/projetos/${projetoId}/ranking/overrides`, { keyword, action, kw_type }).then(r => r.data),
  deleteOverride: (projetoId: string, keyword: string) =>
    api.delete(`/projetos/${projetoId}/ranking/overrides/${encodeURIComponent(keyword)}`).then(r => r.data),
  history: (projetoId: string, keyword?: string) =>
    api.get<RankingHistoryResponse>(
      `/projetos/${projetoId}/ranking/history`,
      { params: keyword ? { keyword } : undefined }
    ).then(r => r.data),
  report: (projetoId: string) =>
    api.get<RankingReportResponse>(`/projetos/${projetoId}/ranking/report`).then(r => r.data),
}

// ── Ranking Report ────────────────────────────────────────────────────────

export interface RankingReportSummary {
  total: number
  rankeando: number
  rankeando_delta: number | null
  gap: number
  gap_delta: number | null
  surpresa: number
  surpresa_delta: number | null
}

export interface RankingTopRow {
  keyword: string
  serp_position: number | null
  sc_position: number | null
  sc_impressions_30d: number | null
}

export interface RankingFellRow {
  keyword: string
  prev_serp: number | null
  curr_serp: number | null
  delta: number
}

export interface RankingRoseRow {
  keyword: string
  prev_serp: number | null
  curr_serp: number | null
  delta: number
}

export interface RankingNewSurpresaRow {
  keyword: string
  sc_impressions_30d: number | null
}

export interface RankingCriticalGapRow {
  keyword: string
  status: string
  sc_impressions_30d: number | null
  sc_position: number | null
}

export interface RankingReportResponse {
  status: 'ok' | 'not_ready'
  mode?: 'baseline' | 'weekly'
  report_date?: string
  current_snapshot_date?: string
  previous_snapshot_date?: string | null
  projeto_id?: string
  projeto_nome?: string
  summary?: RankingReportSummary
  top_rankeando?: RankingTopRow[]
  fell?: RankingFellRow[]
  rose?: RankingRoseRow[]
  new_surpresa?: RankingNewSurpresaRow[]
  critical_gaps?: RankingCriticalGapRow[]
  message?: string
}

// ── SEO Plan ─────────────────────────────────────────────────────────────

export interface SeoPlanKeyword {
  id: number
  keyword: string
  avg_monthly_searches: number | null
}

export interface Competitor {
  url: string
  score: number
  backlink_score?: number | null
  backlink_label?: 'fraco' | 'medio' | 'forte' | null
}

export interface RegionIntel {
  geo_nome: string
  query: string
  competitive_score: number
  difficulty_label: 'baixo' | 'médio' | 'alto' | 'muito_baixa' | 'baixa' | 'media' | 'alta' | 'muito_alta'
  top_competitor_url: string | null
  competitors?: Competitor[]
}

export interface IntelData {
  kw_principal: string
  analisado_em: string
  regioes: RegionIntel[]
}

export interface SeoPlanPage {
  id: number
  plan_id: number
  pesquisa_id: string          // UUID como string
  pesquisa_nome: string
  pesquisa_status: string
  papel: 'principal' | 'servico' | null
  kw_principal_id: number | null
  kw_principal_text: string | null
  kw_principal_volume: number | null
  keywords: SeoPlanKeyword[]
  // Phase 15 — competitive intel enrichment
  competitive_score: number | null
  difficulty_label: 'baixo' | 'médio' | 'alto' | null
  top_competitor_url: string | null
  intel_updated_at: string | null
  intel_data: IntelData | null
}

export interface GeoTarget {
  id: number
  projeto_id: number
  nome: string
  tipo: 'bairro' | 'cidade' | 'estado' | null
  ativo: boolean
  volume_estimado: number | null
  created_at: string
}

export interface GeoTargetCreate {
  nome: string
  tipo?: 'bairro' | 'cidade' | 'estado' | null
  volume_estimado?: number | null
}

export const geoTargetsApi = {
  list: (projetoId: string) =>
    api.get<GeoTarget[]>(`/projetos/${projetoId}/geo-targets`).then(r => r.data),
  create: (projetoId: string, data: GeoTargetCreate) =>
    api.post<GeoTarget>(`/projetos/${projetoId}/geo-targets`, data).then(r => r.data),
  delete: (projetoId: string, geoId: number) =>
    api.delete(`/projetos/${projetoId}/geo-targets/${geoId}`).then(r => r.data),
}

export interface SeoPlan {
  id: number
  projeto_id: string
  status: 'rascunho' | 'pronto'
  created_at: string
  updated_at: string
  pages: SeoPlanPage[]
  pesquisas_sem_plano: string[]
  competitive_intel_pending: boolean
}

export const seoPlanApi = {
  get: (projetoId: string) =>
    api.get<SeoPlan>(`/projetos/${projetoId}/seo-plan`).then(r => r.data),
  generate: (projetoId: string) =>
    api.post<SeoPlan>(`/projetos/${projetoId}/seo-plan/generate`).then(r => r.data),
  updatePage: (projetoId: string, pageId: number, data: { kw_principal_id?: number | null; papel?: string | null }) =>
    api.patch(`/projetos/${projetoId}/seo-plan/pages/${pageId}`, data).then(r => r.data),
  markReady: (projetoId: string) =>
    api.patch<{ ok: boolean; agent_executions_id?: number }>(`/projetos/${projetoId}/seo-plan/ready`).then(r => r.data),
}

// ── Content Review ────────────────────────────────────────────────────────

export interface SectionResult {
  status: 'ok' | 'ajustar' | 'flag' | 'refazer'
  issues?: string[]
}

export interface ReviewReport {
  status: string
  sections: Record<string, SectionResult>
}

export interface ContentPage {
  id: string
  projeto_id: string
  page_slug: string
  page_type: 'home' | 'service' | 'service_region'
  status: 'gerado' | 'revisado' | 'aprovado' | 'revisar'
  review_report: ReviewReport | null
  reviewed_at: string | null
  approved_at: string | null
  created_at: string
  updated_at: string
}

// ─── Pipeline ────────────────────────────────────────────────────────────────

export interface AgentExecution {
  id: number
  agent_name: string
  status: 'pending' | 'in_progress' | 'completed' | 'failed'
  error_message: string | null
  progress_data: Record<string, unknown> | null
  started_at: string | null
  triggered_at: string | null
  completed_at: string | null
  created_at: string
}

export const pipelineApi = {
  get: (projetoId: string) =>
    api.get<AgentExecution[]>(`/projetos/${projetoId}/pipeline`).then(r => r.data),
}

// ─── Auditoria SEO ───────────────────────────────────────────────────────────

export interface AuditCwv {
  lcp_ms: number | null
  cls: number | null
  tbt_ms: number | null
}

export interface AuditSchemaItem {
  valid: boolean
  missing_fields?: string[]
}

export interface AuditCannibalization {
  found: boolean
  pairs: Array<{ slug_a: string; slug_b: string; keyword: string }>
}

export interface AuditData {
  slug: string
  target_url: string
  scores: { performance: number | null; cwv: AuditCwv }
  schema_validation: { local_business: AuditSchemaItem; service: AuditSchemaItem }
  cannibalization: AuditCannibalization
  findings: string[]
  top_actions: string[]
}

export interface AuditResponse {
  status: 'not_found' | 'pending' | 'in_progress' | 'completed' | 'failed'
  execution_id?: number
  started_at?: string | null
  completed_at?: string | null
  data?: AuditData | null
}

export const auditApi = {
  get: (projetoId: string) =>
    api.get<AuditResponse>(`/projetos/${projetoId}/audit`).then(r => r.data),
}

// ─── Content ─────────────────────────────────────────────────────────────────

// ─── Competitor Audit ─────────────────────────────────────────────────────────

export interface CompetitorInfo {
  url: string
  position: number
  domain: string
  domain_age_years: number | null
  domain_created_date: string | null
  title_tag: string | null
  h1: string | null
  h2s: string[]
  estimated_word_count: number
  sections_detected: Record<string, boolean>
  schema_json_ld: string[]
  geo_pages_count: number
  trust_signals: {
    certifications_mentioned: boolean
    has_testimonials: boolean
    has_faq: boolean
    has_cnpj: boolean
    has_google_maps: boolean
    phone_numbers: string[]
  }
  seo_plugin_detected: string | null
  backlink_count: number | null
  avg_domain_rank: number | null
  avg_spam_score: number | null
}

export interface CompetitorAuditMarketGaps {
  benchmark_word_count: number
  required_sections: string[]
  schema_missing: string[]
  geo_pages_benchmark: number
  backlink_benchmark: number | null
  trust_gaps: string[]
  summary: string
}

export interface CompetitorAuditData {
  status: 'not_found' | 'completed'
  slug?: string
  keyword_principal?: string
  generated_at?: string
  competitor_count?: number
  market_gaps?: CompetitorAuditMarketGaps
  competitors?: CompetitorInfo[]
  yaml_path?: string
  updated_at?: string
}

export const competitorAuditApi = {
  get: (projetoId: string) =>
    api.get<CompetitorAuditData>(`/projetos/${projetoId}/competitor-audit`).then(r => r.data),
}

export const contentApi = {
  list: (projetoId: string) =>
    api.get<ContentPage[]>(`/projetos/${projetoId}/content`).then(r => r.data),
  approve: (projetoId: string, pageSlug: string) =>
    api.patch<ContentPage>(`/projetos/${projetoId}/content/${pageSlug}/approve`).then(r => r.data),
  updateStatus: (projetoId: string, pageSlug: string, status: string) =>
    api.patch<ContentPage>(`/projetos/${projetoId}/content/${pageSlug}/status`, { status }).then(r => r.data),
  updateSection: (projetoId: string, pageSlug: string, section: string, status: string, issues: string[]) =>
    api.patch<ContentPage>(`/projetos/${projetoId}/content/${pageSlug}/section`, { section, status, issues }).then(r => r.data),
  deleteSection: (projetoId: string, pageSlug: string, sectionName: string) =>
    api.delete<ContentPage>(`/projetos/${projetoId}/content/${pageSlug}/section/${sectionName}`).then(r => r.data),
  delete: (projetoId: string, pageSlug: string) =>
    api.delete(`/projetos/${projetoId}/content/${pageSlug}`),
}
