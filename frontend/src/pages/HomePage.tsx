import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

import { hasRole, useSession } from '../auth/session'
import { useDrafts } from '../drafts/DraftsProvider'

export function HomePage() {
  const { t } = useTranslation()
  const session = useSession()
  const { drafts } = useDrafts()
  const waiting = drafts.length

  return (
    <section className="home">
      <p className="tagline">{t('home.greeting', { name: session.user.display_name })}</p>
      {session.mfa_setup_required && (
        <p className="warning">
          {t('twoStep.required')} <Link to="/account/two-step">{t('twoStep.link')}</Link>
        </p>
      )}
      <div className="actions">
        <Link to="/contribute" className="action primary">
          <span aria-hidden="true">🎙️</span> {t('home.newRecording')}
        </Link>
        <Link to="/submissions" className="action">
          <span aria-hidden="true">📋</span> {t('home.mySubmissions')}
          {waiting > 0 && <span className="badge">{t('home.onDevice', { count: waiting })}</span>}
        </Link>
        {hasRole(session, 'contributor', 'facilitator', 'reviewer', 'admin') && (
          <Link to="/account/profile" className="action">
            <span aria-hidden="true">👤</span> {t('profile.link')}
          </Link>
        )}
        {hasRole(session, 'researcher', 'admin') && (
          <Link to="/catalogue" className="action">
            <span aria-hidden="true">🔎</span> {t('catalogue.link')}
          </Link>
        )}
        {hasRole(session, 'researcher', 'admin') && (
          <Link to="/datasets" className="action">
            <span aria-hidden="true">📦</span> {t('releases.link')}
          </Link>
        )}
        {hasRole(session, 'admin') && (
          <Link to="/admin/status" className="action">
            <span aria-hidden="true">🩺</span> {t('status.link')}
          </Link>
        )}
        {hasRole(session, 'admin') && (
          <Link to="/admin/jobs" className="action">
            <span aria-hidden="true">🛠️</span> {t('jobs.link')}
          </Link>
        )}
        {hasRole(session, 'admin') && (
          <Link to="/admin/reports" className="action">
            <span aria-hidden="true">🚩</span> {t('reports.link')}
          </Link>
        )}
        {hasRole(session, 'admin') && (
          <Link to="/admin/withdrawals" className="action">
            <span aria-hidden="true">↩️</span> {t('adminWithdrawals.link')}
          </Link>
        )}
      </div>
    </section>
  )
}
