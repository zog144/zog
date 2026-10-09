import {LicenseLink} from '../LicenseLink'
import { FormEvent, useState } from 'react'
import { useAuth } from '../auth/AuthProvider'

export function LoginPage() {
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  async function submit(event: FormEvent) {
    event.preventDefault(); setError('')
    try { await login(username, password) } catch (e) { setError(e instanceof Error ? e.message : 'Login failed') }
  }
  return <main className="login"><form onSubmit={submit}><h1>station-access</h1><label>Username<input autoComplete="username" required value={username} onChange={e => setUsername(e.target.value)} /></label><label>Password<input autoComplete="current-password" required type="password" value={password} onChange={e => setPassword(e.target.value)} /></label><button>Sign in</button>{error && <p className="error">{error}</p>}</form><p><LicenseLink /></p></main>
}
