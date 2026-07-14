import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import Spinner from './Spinner'

export default function ProtectedRoute({ children }) {
  const { user, loading } = useAuth()
  const location = useLocation()

  // Wait for the session check. Redirecting while it is still in flight would
  // bounce a signed-in user to the login page on every refresh.
  if (loading) return <Spinner label="Loading…" />

  if (!user) {
    // Remember where they were headed so login can send them back.
    return <Navigate to="/login" replace state={{ from: location }} />
  }

  return children
}
