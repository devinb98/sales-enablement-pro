import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export default function Nav() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  async function handleLogout() {
    await logout()
    navigate('/login')
  }

  return (
    <header className="nav">
      <Link to={user ? '/deals' : '/login'} className="nav__brand">
        <span className="nav__mark">SE</span>
        Sales Enablement Pro
      </Link>

      {user && (
        <div className="nav__right">
          <span className="nav__user">{user.name}</span>
          <button type="button" className="btn btn--ghost" onClick={handleLogout}>
            Log out
          </button>
        </div>
      )}
    </header>
  )
}
