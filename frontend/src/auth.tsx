import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { get, getToken, login as apiLogin, setToken, type Session } from './api'

interface AuthState {
  session: Session | null
  loading: boolean
  can: (permission: string) => boolean
  login: (u: string, p: string) => Promise<void>
  logout: () => void
}

const Ctx = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(!!getToken())

  useEffect(() => {
    if (!getToken()) return
    get<Session>('/api/v1/auth/me').then(setSession).catch(() => setToken(null)).finally(() => setLoading(false))
  }, [])

  const login = useCallback(async (u: string, p: string) => setSession(await apiLogin(u, p)), [])
  const logout = useCallback(() => { setToken(null); setSession(null) }, [])
  const can = useCallback((perm: string) => !!session?.permissions.includes(perm), [session])

  return <Ctx.Provider value={{ session, loading, can, login, logout }}>{children}</Ctx.Provider>
}

export function useAuth(): AuthState {
  const c = useContext(Ctx)
  if (!c) throw new Error('useAuth outside AuthProvider')
  return c
}

export const ROLE_LABEL: Record<string, string> = {
  FRAUD_ANALYST: 'Fraud analyst', AML_ANALYST: 'AML analyst', COMPLIANCE_OFFICER: 'Compliance officer',
  INVESTIGATION_MANAGER: 'Investigation manager', OPERATIONS_MANAGER: 'Operations manager', ADMIN: 'Administrator',
}
