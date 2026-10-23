import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import * as api from '../api/endpoints'
import type { AdminUser, Role } from '../api/types'
import { hasRole, useSession } from '../auth/session'
import { ErrorMessage } from '../components/ErrorMessage'

const STAFF_ROLES: Role[] = ['facilitator', 'reviewer', 'researcher', 'admin']

/** A link shown once: the admin copies it and sends it to the person. */
function OneTimeLink({ url, expiresAt }: { url: string; expiresAt: string }) {
  const { t, i18n } = useTranslation()
  return (
    <div className="note" role="status">
      <p>{t('users.linkOnce')}</p>
      <input readOnly value={url} onFocus={(e) => e.target.select()} aria-label={t('users.linkLabel')} />
      <p>
        {t('users.expires', {
          when: new Date(expiresAt).toLocaleString(i18n.resolvedLanguage),
        })}
      </p>
    </div>
  )
}

/** Admins help people who forgot their password, and invite staff (ADR-028). */
export function AdminUsersPage() {
  const { t } = useTranslation()
  const session = useSession()
  const [query, setQuery] = useState('')
  const [users, setUsers] = useState<AdminUser[] | null>(null)
  const [reset, setReset] = useState<{ userId: string; url: string; expiresAt: string } | null>(
    null,
  )
  const [role, setRole] = useState<Role>('facilitator')
  const [invite, setInvite] = useState<{ url: string; expiresAt: string } | null>(null)
  const [error, setError] = useState<unknown>(null)

  if (!hasRole(session, 'admin')) return <p className="note">{t('status.adminOnly')}</p>

  const search = async (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    setReset(null)
    try {
      setUsers(await api.findUsers(query))
    } catch (failure) {
      setError(failure)
    }
  }

  const makeReset = async (user: AdminUser) => {
    if (!window.confirm(t('users.confirmReset', { username: user.username }))) return
    setError(null)
    try {
      const made = await api.createPasswordReset(user.id)
      setReset({ userId: user.id, url: made.reset_url, expiresAt: made.expires_at })
    } catch (failure) {
      setError(failure)
    }
  }

  const makeInvite = async (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    try {
      const made = await api.createInvitation(role)
      setInvite({ url: made.invite_url, expiresAt: made.expires_at })
    } catch (failure) {
      setError(failure)
    }
  }

  return (
    <section>
      <h1>{t('users.title')}</h1>
      <ErrorMessage error={error} />

      <h2>{t('users.forgotTitle')}</h2>
      <p className="note">{t('users.forgotIntro')}</p>
      <form className="form" onSubmit={(event) => void search(event)}>
        <label>
          {t('users.search')}
          <input value={query} onChange={(e) => setQuery(e.target.value)} required />
        </label>
        <button type="submit" className="action">
          {t('users.find')}
        </button>
      </form>
      {users && users.length === 0 && <p className="note">{t('users.none')}</p>}
      {users && users.length > 0 && (
        <ul className="list">
          {users.map((user) => (
            <li key={user.id}>
              <strong>{user.username}</strong> · {user.display_name} ·{' '}
              {user.roles.map((grant) => t(`roles.${grant.role}`)).join(', ')}
              {user.status !== 'active' && ` · ${user.status}`}{' '}
              <button type="button" className="link-button" onClick={() => void makeReset(user)}>
                {t('users.makeReset')}
              </button>
              {reset?.userId === user.id && (
                <OneTimeLink url={reset.url} expiresAt={reset.expiresAt} />
              )}
            </li>
          ))}
        </ul>
      )}

      <h2>{t('users.inviteTitle')}</h2>
      <p className="note">{t('users.inviteIntro')}</p>
      <form className="form" onSubmit={(event) => void makeInvite(event)}>
        <label>
          {t('users.role')}
          <select value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {STAFF_ROLES.map((value) => (
              <option key={value} value={value}>
                {t(`roles.${value}`)}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" className="action">
          {t('users.makeInvite')}
        </button>
      </form>
      {invite && <OneTimeLink url={invite.url} expiresAt={invite.expiresAt} />}
    </section>
  )
}
