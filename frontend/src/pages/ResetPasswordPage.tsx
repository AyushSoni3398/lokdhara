import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useLocation } from 'react-router'

import * as api from '../api/endpoints'
import { ErrorMessage } from '../components/ErrorMessage'
import { PASSWORD_MIN_LENGTH } from './SignupPage'

/** Opens a reset link an admin made (`/reset-password#<token>`). */
export function ResetPasswordPage() {
  const { t } = useTranslation()
  const token = useLocation().hash.slice(1)
  const [password, setPassword] = useState('')
  const [repeat, setRepeat] = useState('')
  const [error, setError] = useState<unknown>(token ? null : 'reset_invalid')
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (password !== repeat) {
      setError('passwords_differ')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await api.resetPassword(token, password)
      setDone(true)
    } catch (failure) {
      setError(failure)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section>
      <h1>{t('reset.title')}</h1>
      {done ? (
        <p role="status">
          {t('reset.done')} <Link to="/login">{t('login.submit')}</Link>
        </p>
      ) : token ? (
        <form className="form" onSubmit={(event) => void submit(event)}>
          <label>
            {t('reset.newPassword')}
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={PASSWORD_MIN_LENGTH}
              autoComplete="new-password"
              required
            />
            <small>{t('signup.passwordHint', { count: PASSWORD_MIN_LENGTH })}</small>
          </label>
          <label>
            {t('signup.repeat')}
            <input
              type="password"
              value={repeat}
              onChange={(e) => setRepeat(e.target.value)}
              autoComplete="new-password"
              required
            />
          </label>
          <ErrorMessage error={error} />
          <button type="submit" className="action primary" disabled={busy}>
            {t('reset.submit')}
          </button>
        </form>
      ) : (
        <ErrorMessage error={error} />
      )}
    </section>
  )
}
