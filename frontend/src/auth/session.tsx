import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router'

import { setCsrfToken } from '../api/client'
import * as api from '../api/endpoints'
import type { Role, Session, SignupRequest } from '../api/types'

type State =
  | { status: 'loading' }
  | { status: 'signedOut' }
  | { status: 'signedIn'; session: Session }

interface Auth {
  state: State
  signIn: (username: string, password: string, code?: string) => Promise<void>
  /** Makes a contributor account and signs it in. */
  signUp: (details: SignupRequest) => Promise<void>
  signOut: () => Promise<void>
  /** Fetches the session again, e.g. after two-step sign-in gives back the admin role. */
  refresh: () => Promise<void>
}

const AuthContext = createContext<Auth | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>({ status: 'loading' })

  const accept = useCallback((session: Session) => {
    setCsrfToken(session.csrf_token)
    setState({ status: 'signedIn', session })
  }, [])

  useEffect(() => {
    // Any failure, including being offline at start-up, shows the sign-in page. Drafts stay
    // safe on the device and upload after the next sign-in.
    api.me().then(accept, () => setState({ status: 'signedOut' }))
  }, [accept])

  const signIn = useCallback(
    async (username: string, password: string, code?: string) =>
      accept(await api.login(username, password, code)),
    [accept],
  )
  const signUp = useCallback(
    async (details: SignupRequest) => accept(await api.signup(details)),
    [accept],
  )
  const refresh = useCallback(async () => accept(await api.me()), [accept])
  const signOut = useCallback(async () => {
    try {
      await api.logout()
    } finally {
      setCsrfToken(null)
      setState({ status: 'signedOut' })
    }
  }, [])

  const value = useMemo(
    () => ({ state, signIn, signUp, signOut, refresh }),
    [state, signIn, signUp, signOut, refresh],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): Auth {
  const auth = useContext(AuthContext)
  if (!auth) throw new Error('useAuth needs an AuthProvider')
  return auth
}

export function useSession(): Session {
  const { state } = useAuth()
  if (state.status !== 'signedIn') throw new Error('useSession needs a signed-in user')
  return state.session
}

export function hasRole(session: Session, ...roles: Role[]): boolean {
  return session.roles.some((grant) => roles.includes(grant.role))
}

/** Shows the page only when signed in; otherwise sends the person to the sign-in page. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { state } = useAuth()
  const location = useLocation()
  if (state.status === 'loading') return null
  if (state.status === 'signedOut') {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  }
  return children
}
