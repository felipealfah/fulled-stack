import { Navigate, Outlet } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { authApi, getToken } from '../lib/auth'

/**
 * Guard global: se AUTH_ENABLED no backend e não há token, manda para /login.
 * Com auth desativada (dev local), passa direto — comportamento idêntico ao atual.
 */
export function RequireAuth() {
  const { data: status, isLoading } = useQuery({
    queryKey: ['auth-status'],
    queryFn: authApi.status,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center">
        <span className="text-gray-500 font-mono text-sm">Carregando…</span>
      </div>
    )
  }

  if (status?.auth_enabled && !getToken()) {
    return <Navigate to="/login" replace />
  }

  return <Outlet />
}
