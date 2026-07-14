import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { api } from '../api/client'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  // Starts true: on a hard refresh we do not yet know whether there is a live
  // session. Rendering the login page before /api/me answers would flash the
  // login form at an already-authenticated user, then yank it away.
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api
      .me()
      .then(setUser)
      .catch(() => setUser(null)) // 401 simply means "not signed in"
      .finally(() => setLoading(false))
  }, [])

  const login = useCallback(async (credentials) => {
    const account = await api.login(credentials)
    setUser(account)
    return account
  }, [])

  const signup = useCallback(async (details) => {
    const account = await api.signup(details)
    setUser(account)
    return account
  }, [])

  const logout = useCallback(async () => {
    await api.logout()
    setUser(null)
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
