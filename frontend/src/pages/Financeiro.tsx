import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { financeiroApi } from '../lib/api'

const TIPO_CFG: Record<string, { label: string; cls: string }> = {
  rank_rent:         { label: 'Rank & Rent', cls: 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30' },
  infoproduto:       { label: 'Infoproduto',  cls: 'bg-violet-500/10 text-violet-400 border border-violet-500/30' },
  youtube_faceless:  { label: 'YouTube',      cls: 'bg-red-500/10 text-red-400 border border-red-500/30' },
  facebook_faceless: { label: 'Facebook',     cls: 'bg-blue-500/10 text-blue-400 border border-blue-500/30' },
  prospeccao:        { label: 'Prospecção',   cls: 'bg-amber-500/10 text-amber-400 border border-amber-500/30' },
}

const brl = (v: number | null | undefined) =>
  (Number(v) || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', maximumFractionDigits: 0 })

function Card({ titulo, valor, detalhe, cls }: { titulo: string; valor: string; detalhe?: string; cls: string }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl px-5 py-4 flex-1 min-w-[180px]">
      <p className="text-xs font-mono text-gray-500 uppercase tracking-wider">{titulo}</p>
      <p className={`font-mono font-bold text-2xl mt-1 ${cls}`}>{valor}</p>
      {detalhe && <p className="text-[11px] font-mono text-gray-600 mt-1">{detalhe}</p>}
    </div>
  )
}

export function Financeiro() {
  const navigate = useNavigate()
  const { data, isLoading, error, dataUpdatedAt } = useQuery({
    queryKey: ['financeiro'],
    queryFn: () => financeiroApi.resumo(),
    refetchInterval: 15000,
  })

  if (isLoading) return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center">
      <p className="text-gray-600 text-sm font-mono">Carregando financeiro...</p>
    </div>
  )

  if (error || !data) return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center">
      <p className="text-red-400 text-sm font-mono">Erro ao carregar. Verifique a conexão com a API.</p>
    </div>
  )

  const p = data.prospeccao

  return (
    <div className="min-h-screen bg-gray-950">
      <header className="border-b border-gray-800 px-6 py-5">
        <div className="max-w-4xl mx-auto">
          <h1 className="font-mono font-semibold tracking-tight text-gray-100">Financeiro</h1>
          <p className="text-xs text-gray-600 font-mono mt-0.5">
            Receita consolidada de todas as operações
            {dataUpdatedAt ? ` · sync ${new Date(dataUpdatedAt).toLocaleTimeString('pt-BR')}` : ''}
          </p>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-6 py-6 flex flex-col gap-6">
        {/* Cards */}
        <div className="flex gap-3 flex-wrap">
          <Card titulo="MRR total" valor={`${brl(data.mrr_total)}/mês`}
                detalhe={`projetos ${brl(data.mrr_projetos)} · prospecção ${brl(data.mrr_prospeccao)}`}
                cls="text-teal-300" />
          <Card titulo="One-off prospecção" valor={brl(Number(p.receita_fechada))}
                detalhe={`${p.fechados} fechado(s)`} cls="text-emerald-400" />
          <Card titulo="A receber" valor={brl(Number(p.a_receber))}
                detalhe="fechados ainda não pagos" cls="text-amber-400" />
          <Card titulo="Contratos" valor={`${p.contratos_assinados}✓`}
                detalhe={`${p.contratos_enviados} enviado(s), ${p.contratos_assinados} assinado(s)`} cls="text-gray-200" />
        </div>

        {/* Receita recorrente por projeto */}
        <section className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <div className="px-5 py-3 border-b border-gray-800">
            <h2 className="text-xs font-mono font-semibold uppercase tracking-wider text-gray-500">
              Receita recorrente por projeto
            </h2>
          </div>
          {data.projetos.length === 0 && p.manutencoes.length === 0 ? (
            <p className="px-5 py-8 text-sm font-mono text-gray-600 text-center">
              Nenhuma receita recorrente registrada — preencha <span className="text-gray-400">receita mensal</span> nos projetos ou feche clientes com manutenção na prospecção.
            </p>
          ) : (
            <table className="w-full text-sm font-mono">
              <tbody>
                {data.projetos.map(pr => (
                  <tr key={pr.id}
                      onClick={() => navigate(`/projetos/${pr.id}`)}
                      className="border-b border-gray-800/60 hover:bg-gray-800/40 cursor-pointer">
                    <td className="px-5 py-3 text-gray-200">{pr.projeto_nome}</td>
                    <td className="px-3 py-3">
                      <span className={`text-[11px] px-2 py-0.5 rounded-full whitespace-nowrap ${TIPO_CFG[pr.tipo]?.cls ?? 'bg-gray-800 text-gray-500'}`}>
                        {TIPO_CFG[pr.tipo]?.label ?? pr.tipo}
                      </span>
                    </td>
                    <td className="px-3 py-3 text-gray-600 text-xs">{pr.status}</td>
                    <td className="px-5 py-3 text-right text-teal-300 font-semibold whitespace-nowrap">{brl(pr.receita_mensal)}/mês</td>
                  </tr>
                ))}
                {p.manutencoes.map(m => (
                  <tr key={m.slug}
                      onClick={() => navigate(m.projeto_id ? `/projetos/${m.projeto_id}/prospeccao` : '/prospeccao')}
                      className="border-b border-gray-800/60 hover:bg-gray-800/40 cursor-pointer">
                    <td className="px-5 py-3 text-gray-200">{m.nome} <span className="text-gray-600 text-xs">({m.cidade})</span></td>
                    <td className="px-3 py-3">
                      <span className="text-[11px] px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/30 whitespace-nowrap">
                        Manutenção
                      </span>
                    </td>
                    <td className="px-3 py-3 text-xs">
                      <span className={m.pago ? 'text-emerald-400' : 'text-amber-400'}>{m.pago ? 'pago' : 'a receber'}</span>
                    </td>
                    <td className="px-5 py-3 text-right text-teal-300 font-semibold whitespace-nowrap">{brl(m.manutencao_mensal)}/mês</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <p className="text-[11px] font-mono text-gray-700">
          MRR de projetos vem do campo <span className="text-gray-500">receita mensal</span> (editável no detalhe de cada projeto).
          Manutenções vêm dos leads fechados da prospecção.
        </p>
      </main>
    </div>
  )
}
