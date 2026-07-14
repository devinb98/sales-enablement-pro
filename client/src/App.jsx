import { Navigate, Route, Routes } from 'react-router-dom'
import Nav from './components/Nav'
import ProtectedRoute from './components/ProtectedRoute'
import Deals from './pages/Deals'
import DealDetail from './pages/DealDetail'
import Login from './pages/Login'
import PlanView from './pages/PlanView'
import Signup from './pages/Signup'
import './App.css'

export default function App() {
  return (
    <>
      <Nav />
      <main>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />

          <Route
            path="/deals"
            element={
              <ProtectedRoute>
                <Deals />
              </ProtectedRoute>
            }
          />
          <Route
            path="/deals/:id"
            element={
              <ProtectedRoute>
                <DealDetail />
              </ProtectedRoute>
            }
          />
          <Route
            path="/plans/:id"
            element={
              <ProtectedRoute>
                <PlanView />
              </ProtectedRoute>
            }
          />

          <Route path="/" element={<Navigate to="/deals" replace />} />
          <Route path="*" element={<Navigate to="/deals" replace />} />
        </Routes>
      </main>
    </>
  )
}
