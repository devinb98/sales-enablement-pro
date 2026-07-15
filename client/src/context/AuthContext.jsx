import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { api, auth } from '../api/client'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  // Starts true: on a hard refresh we do not yet know whether there is a live
  // session. Rendering the login page before /api/me answers would flash the
  // login form at an already-authenticated user, then yank it away.
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // Only ask the server who we are if we hold a token; otherwise we already
    // know we are signed out and can skip a guaranteed 401.
    if (!auth.get()) {
      setLoading(false)
      return
    }
    api
      .me()
      .then(setUser)
      .catch(() => {
        // Token missing, expired, or rejected — treat as signed out.
        auth.clear()
        setUser(null)
      })
      .finally(() => setLoading(false))
  }, [])

  const login = useCallback(async (credentials) => {
    const account = await api.login(credentials)
    auth.set(account.token)
    setUser(account)
    return account
  }, [])

  const signup = useCallback(async (details) => {
    const account = await api.signup(details)
    auth.set(account.token)
    setUser(account)
    return account
  }, [])

  const logout = useCallback(async () => {
    // Tell the server, but the token in localStorage is what actually keeps us
    // logged in, so clear it regardless of how the request goes.
    try {
      await api.logout()
    } finally {
      auth.clear()
      setUser(null)
    }
  }, [])

  return (
    <AuthContext.Provider value={{ user, loading, login, signup, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (context === null) {
    throw new Error('useAuth must be used inside an AuthProvider')
  }
  return context
}
