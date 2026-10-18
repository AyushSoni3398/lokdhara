import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate, useLocation, useNavigate } from 'react-router'

import { errorCode } from '../api/client'
import { useAuth } from '../auth/session'
import { ErrorMessage } from '../components/ErrorMessage'

export function LoginPage() {
  const { t } = useTranslation()
  const { state, signIn } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  // Shown once the server says the password was right and a second step is needed.
  const [needsCode, setNeedsCode] = useState(false)
  const [code, setCode] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const from = (location.state as { from?: string } | null)?.from ?? '/'

  if (state.status === 'signedIn') return <Navigate to={from} replace />

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await signIn(username, password, needsCode ? code : undefined)
      void navigate(from, { replace: true })
    } catch (failure) {
      if (errorCode(failure) === 'mfa_required') setNeedsCode(true)
      else setError(failure)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section>
      <h1>{t('login.title')}</h1>
      <p className="note">{t('login.inviteOnly')}</p>
      <form className="form" onSubmit={(event) => void submit(event)}>
        <label>
          {t('login.username')}
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoCapitalize="none"
            required
          />
        </label>
        <label>
          {t('login.password')}
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        {needsCode && (
          <>
            <p className="note">{t('login.codeHint')}</p>
            <label>
              {t('login.code')}
              <input
                value={code}
                onChange={(e) => setCode(e.target.value)}
                autoComplete="one-time-code"
                autoCapitalize="characters"
                inputMode="text"
                maxLength={20}
                autoFocus
                required
              />
            </label>
          </>
        )}
        <ErrorMessage error={error} />
        <button type="submit" className="action primary" disabled={busy}>
          {t('login.submit')}
        </button>
      </form>
    </section>
  )
}
