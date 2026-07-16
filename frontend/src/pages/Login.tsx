import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { authApi, setSession, getToken } from '../lib/auth'

export function Login() {
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const { data: status } = useQuery({
    queryKey: ['auth-status'],
    queryFn: authApi.status,
    staleTime: 5 * 60 * 1000,
  })

  // Auth desativada (dev local) ou já logado → segue para o dashboard
  if (status && !status.auth_enabled) {
    navigate('/projetos', { replace: true })
    return null
  }
  if (getToken()) {
    navigate('/projetos', { replace: true })
    return null
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const data = await authApi.login(username, password)
      setSession(data.token, data.user)
      navigate('/projetos', { replace: true })
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Erro ao entrar — tente novamente'
      setError(detail)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold font-mono text-gray-100">
            Full<span className="text-emerald-400">ED</span>
          </h1>
          <p className="text-sm text-gray-500 font-mono mt-1">Pipeline LeadGen — Board</p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="bg-gray-900 border border-gray-800 rounded-xl p-6 space-y-4"
        >
          <div>
            <label
              htmlFor="login-user"
              className="block text-xs font-mono text-gray-400 mb-1.5"
            >
              Usuário
            </label>
            <input
              id="login-user"
              type="email"
              autoComplete="username"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full bg-gray-950 border border-gray-700 rounded-lg px-3 py-2.5 text-sm font-mono text-gray-100 placeholder-gray-600 focus:outline-none focus:border-emerald-500 transition-colors"
              placeholder="voce@fulled.com.br"
            />
          </div>

          <div>
            <label
              htmlFor="login-password"
              className="block text-xs font-mono text-gray-400 mb-1.5"
            >
              Senha
            </label>
            <input
              id="login-password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-gray-950 border border-gray-700 rounded-lg px-3 py-2.5 text-sm font-mono text-gray-100 placeholder-gray-600 focus:outline-none focus:border-emerald-500 transition-colors"
              placeholder="••••••••"
            />
          </div>

          {error && (
            <p
              role="alert"
              className="text-sm font-mono text-red-400 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2"
            >
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-emerald-600 hover:bg-emerald-500 disabled:bg-emerald-800 disabled:cursor-not-allowed text-white font-mono font-semibold text-sm py-2.5 rounded-lg transition-colors"
          >
            {loading ? 'Entrando…' : 'Entrar'}
          </button>
        </form>

        <p className="text-center text-xs text-gray-600 font-mono mt-6">
          FullED Estratégias Digitais
        </p>
      </div>
    </div>
  )
}
