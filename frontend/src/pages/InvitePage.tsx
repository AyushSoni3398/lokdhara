import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate, useLocation } from 'react-router'

import * as api from '../api/endpoints'
import { useAuth } from '../auth/session'
import { ErrorMessage } from '../components/ErrorMessage'
import { AccountFields, emptyAccount } from './SignupPage'

/** Opens an invitation link (`/invite#<token>`): staff roles still come this way (ADR-028). */
export function InvitePage() {
  const { t, i18n } = useTranslation()
  const { state, signIn } = useAuth()
  // The token is in the fragment, so it never reaches a server log.
  const token = useLocation().hash.slice(1)
  const [account, setAccount] = useState(emptyAccount)
  const [error, setError] = useState<unknown>(token ? null : 'invitation_invalid')
  const [busy, setBusy] = useState(false)

  if (state.status === 'signedIn') return <Navigate to="/" replace />

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (account.password !== account.repeat) {
      setError('passwords_differ')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await api.acceptInvitation(token, {
        username: account.username.trim(),
        display_name: account.displayName.trim(),
        password: account.password,
        locale: i18n.resolvedLanguage === 'en' ? 'en' : 'hi',
      })
      // Signing in sends the person on to the home page.
      await signIn(account.username.trim(), account.password)
    } catch (failure) {
      setError(failure)
      setBusy(false)
    }
  }

  return (
    <section>
      <h1>{t('invite.title')}</h1>
      <p className="note">{t('invite.intro')}</p>
      {token && (
        <form className="form" onSubmit={(event) => void submit(event)}>
          <AccountFields value={account} onChange={setAccount} />
          <ErrorMessage error={error} />
          <button type="submit" className="action primary" disabled={busy}>
            {t('signup.submit')}
          </button>
        </form>
      )}
      {!token && <ErrorMessage error={error} />}
      <p>
        <Link to="/login">{t('login.submit')}</Link>
      </p>
    </section>
  )
}
