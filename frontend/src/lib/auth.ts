import { api } from './api'

const TOKEN_KEY = 'fulled_token'
const USER_KEY = 'fulled_user'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function getUser(): string | null {
  return localStorage.getItem(USER_KEY)
}

export function setSession(token: string, user: string) {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, user)
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

export interface AuthStatus {
  auth_enabled: boolean
}

export const authApi = {
  status: () => api.get<AuthStatus>('/auth/status').then((r) => r.data),
  login: (username: string, password: string) =>
    api
      .post<{ token: string; user: string; expires_at: number }>('/auth/login', {
        username,
        password,
      })
      .then((r) => r.data),
}

export function logout() {
  clearSession()
  window.location.href = '/login'
}
