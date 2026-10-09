import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, type SessionUser } from '../api'

type AuthContextValue = {
  loading: boolean
  user: SessionUser | null
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
  refresh: () => Promise<void>
}
const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [loading, setLoading] = useState(true)
  const [user, setUser] = useState<SessionUser | null>(null)
  useEffect(() => { api.session().then(s => setUser(s.authenticated ? s.user : null)).catch(() => setUser(null)).finally(() => setLoading(false)) }, [])
  const value = useMemo<AuthContextValue>(() => ({
    loading,
    user,
    refresh: async () => { const s = await api.session(); setUser(s.authenticated ? s.user : null) },
    login: async (username, password) => { const s = await api.login(username, password); setUser(s.authenticated ? s.user : null) },
    logout: async () => { await api.logout(); setUser(null) },
  }), [loading, user])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside AuthProvider')
  return value
}
