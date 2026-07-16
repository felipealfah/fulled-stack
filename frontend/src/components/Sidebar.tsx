import { NavLink } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { projetosApi, type Projeto } from '../lib/api'
import { getToken, getUser, logout } from '../lib/auth'

function LogoutButton() {
  const token = getToken()
  if (!token) return null
  return (
    <div className="mt-auto pt-4 border-t border-gray-800">
      <div className="px-3 py-1 text-xs font-mono text-gray-600 truncate">{getUser()}</div>
      <button
        onClick={logout}
        className="w-full text-left px-3 py-2 rounded-lg text-sm font-mono text-gray-400 hover:text-red-400 hover:bg-red-500/10 transition-colors"
      >
        Sair
      </button>
    </div>
  )
}

function RankingProjectList() {
  const { data: projetos } = useQuery({
    queryKey: ['projetos', 'publicado'],
    queryFn: () => projetosApi.listByStatus('publicado'),
    staleTime: 60 * 1000,
  })

  if (!projetos || projetos.length === 0) return null

  return (
    <div className="ml-3 mt-0.5 flex flex-col gap-0.5">
      {projetos.map((p: Projeto) => (
        <NavLink
          key={p.id}
          to={`/projetos/${p.id}/ranking`}
          className={({ isActive }) =>
            `px-3 py-1.5 rounded text-xs font-mono transition-colors truncate ${
              isActive
                ? 'text-emerald-400 bg-emerald-500/10'
                : 'text-gray-500 hover:text-gray-300 hover:bg-gray-800/50'
            }`
          }
        >
          {p.projeto_nome}
        </NavLink>
      ))}
    </div>
  )
}


export function Sidebar() {

  return (
    <aside className="w-56 shrink-0 border-r border-gray-800 bg-gray-900 flex flex-col">
      <div className="px-4 py-5 border-b border-gray-800">
        <span className="font-mono font-bold text-sm text-gray-100 tracking-tight">FullED</span>
        <span className="font-mono text-xs text-gray-600 ml-1">/ AIOS</span>
      </div>

      <nav className="flex-1 px-2 py-3 flex flex-col gap-0.5">
        <NavLink
          to="/"
          end
          className={({ isActive }) =>
            `flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-mono transition-colors ${
              isActive
                ? 'text-emerald-400 bg-emerald-500/10'
                : 'text-gray-400 hover:text-gray-100 hover:bg-gray-800'
            }`
          }
        >
          Home
        </NavLink>

        <NavLink
          to="/kw-planner"
          className={({ isActive }) =>
            `flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-mono transition-colors ${
              isActive
                ? 'text-emerald-400 bg-emerald-500/10'
                : 'text-gray-400 hover:text-gray-100 hover:bg-gray-800'
            }`
          }
        >
          Kw Planner
        </NavLink>

        <NavLink
          to="/projetos"
          className={({ isActive }) =>
            `flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-mono transition-colors ${
              isActive
                ? 'text-emerald-400 bg-emerald-500/10'
                : 'text-gray-400 hover:text-gray-100 hover:bg-gray-800'
            }`
          }
        >
          Projetos
        </NavLink>

        {/* Ranking — lista projetos publicados */}
        <div>
          <span className="flex items-center gap-2 px-3 py-2 text-sm font-mono text-gray-400 select-none">
            Ranking
          </span>
          <RankingProjectList />
        </div>

        <span
          className="flex items-center gap-2 px-3 py-2 text-sm font-mono text-gray-700 cursor-default select-none rounded-lg"
        >
          Sites
          <span className="text-[10px] font-mono bg-gray-800 text-gray-600 border border-gray-700 px-1.5 py-0.5 rounded">
            em breve
          </span>
        </span>

        <NavLink
          to="/prospeccao"
          className={({ isActive }) =>
            `flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-mono transition-colors ${
              isActive
                ? 'text-amber-400 bg-amber-500/10'
                : 'text-gray-400 hover:text-gray-100 hover:bg-gray-800'
            }`
          }
        >
          Prospecção
        </NavLink>

        <NavLink
          to="/financeiro"
          className={({ isActive }) =>
            `flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-mono transition-colors ${
              isActive
                ? 'text-teal-400 bg-teal-500/10'
                : 'text-gray-400 hover:text-gray-100 hover:bg-gray-800'
            }`
          }
        >
          Financeiro
        </NavLink>

        <LogoutButton />
      </nav>
    </aside>
  )
}
