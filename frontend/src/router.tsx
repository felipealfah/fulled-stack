import { Routes, Route, Navigate } from 'react-router-dom'
import { Layout } from './components/Layout'
import { RequireAuth } from './components/RequireAuth'
import { Login } from './pages/Login'
import { KwPlannerGate2 } from './pages/KwPlannerGate2'
import { Projetos } from './pages/Projetos'
import { ProjetoDetail } from './pages/ProjetoDetail'
import { ProjetoRanking } from './pages/ProjetoRanking'
import { ProjetoPipeline } from './pages/ProjetoPipeline'
import { SeoPlan } from './pages/SeoPlan'
import { SeoAuditoria } from './pages/SeoAuditoria'
import { RankingRelatorio } from './pages/RankingRelatorio'
import { Sites } from './pages/Sites'
import { ContentReview } from './pages/ContentReview'
import { CompetitorAudit } from './pages/CompetitorAudit'
import { Prospeccao } from './pages/Prospeccao'
import { Financeiro } from './pages/Financeiro'

export function AppRouter() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<RequireAuth />}>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/projetos" replace />} />
        <Route path="/kw-planner" element={<KwPlannerGate2 />} />
        <Route path="/kw-planner/gate2" element={<Navigate to="/kw-planner" replace />} />
        <Route path="/projetos" element={<Projetos />} />
        <Route path="/projetos/:id" element={<ProjetoDetail />} />
        <Route path="/projetos/:id/ranking" element={<ProjetoRanking />} />
        <Route path="/projetos/:id/seo-plan" element={<SeoPlan />} />
        <Route path="/projetos/:id/content" element={<ContentReview />} />
        <Route path="/projetos/:id/relatorio" element={<RankingRelatorio />} />
        <Route path="/projetos/:id/competitor-audit" element={<CompetitorAudit />} />
        <Route path="/projetos/:id/auditoria" element={<SeoAuditoria />} />
        <Route path="/projetos/:id/pipeline" element={<ProjetoPipeline />} />
        <Route path="/projetos/:id/prospeccao" element={<Prospeccao />} />
        <Route path="/sites" element={<Sites />} />
        <Route path="/prospeccao" element={<Prospeccao />} />
        <Route path="/financeiro" element={<Financeiro />} />
      </Route>
      </Route>
    </Routes>
  )
}
