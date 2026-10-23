import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate, useNavigate } from 'react-router'

import { useAuth } from '../auth/session'
import { ErrorMessage } from '../components/ErrorMessage'

/** Same rule as the server: 3 to 40 letters, digits, dot, dash or underscore. */
export const USERNAME_PATTERN = '[A-Za-z0-9][A-Za-z0-9._\\-]{2,39}'
export const PASSWORD_MIN_LENGTH = 10

export interface Account {
  username: string
  displayName: string
  password: string
  repeat: string
}

export const emptyAccount = (): Account => ({
  username: '',
  displayName: '',
  password: '',
  repeat: '',
})

/** The account fields shared by public sign-up and invitations. */
export function AccountFields({
  value,
  onChange,
}: {
  value: Account
  onChange: (value: Account) => void
}) {
  const { t } = useTranslation()
  const set = (changes: Partial<Account>) => onChange({ ...value, ...changes })
  return (
    <>
      <label>
        {t('signup.displayName')}
        <input
          value={value.displayName}
          onChange={(e) => set({ displayName: e.target.value })}
          maxLength={80}
          autoComplete="name"
          required
        />
        <small>{t('signup.displayNameHint')}</small>
      </label>
      <label>
        {t('login.username')}
        <input
          value={value.username}
          onChange={(e) => set({ username: e.target.value })}
          pattern={USERNAME_PATTERN}
          maxLength={40}
          autoComplete="username"
          autoCapitalize="none"
          required
        />
        <small>{t('signup.usernameHint')}</small>
      </label>
      <label>
        {t('login.password')}
        <input
          type="password"
          value={value.password}
          onChange={(e) => set({ password: e.target.value })}
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
          value={value.repeat}
          onChange={(e) => set({ repeat: e.target.value })}
          autoComplete="new-password"
          required
        />
      </label>
    </>
  )
}

export function SignupPage() {
  const { t, i18n } = useTranslation()
  const { state, signUp } = useAuth()
  const navigate = useNavigate()
  const [account, setAccount] = useState(emptyAccount)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  if (state.status === 'signedIn' && !busy) return <Navigate to="/" replace />

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (account.password !== account.repeat) {
      setError('passwords_differ')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await signUp({
        username: account.username.trim(),
        display_name: account.displayName.trim(),
        password: account.password,
        locale: i18n.resolvedLanguage === 'en' ? 'en' : 'hi',
      })
      // Next: the person's own profile and consent, asked once (ADR-028).
      void navigate('/account/profile?setup=1', { replace: true })
    } catch (failure) {
      setError(failure)
      setBusy(false)
    }
  }

  return (
    <section>
      <h1>{t('signup.title')}</h1>
      <p className="note">{t('signup.intro')}</p>
      <form className="form" onSubmit={(event) => void submit(event)}>
        <AccountFields value={account} onChange={setAccount} />
        <ErrorMessage error={error} />
        <button type="submit" className="action primary" disabled={busy}>
          {t('signup.submit')}
        </button>
      </form>
      <p>
        {t('signup.haveAccount')} <Link to="/login">{t('login.submit')}</Link>
      </p>
    </section>
  )
}
