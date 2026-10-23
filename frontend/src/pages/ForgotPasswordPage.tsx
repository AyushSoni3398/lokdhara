import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

/**
 * Accounts have no email or phone check (ADR-028), so a reset link comes from an admin, who
 * first makes sure the request is really from the account's owner.
 */
export function ForgotPasswordPage() {
  const { t } = useTranslation()
  return (
    <section>
      <h1>{t('forgot.title')}</h1>
      <p>{t('forgot.body')}</p>
      <p className="note">{t('forgot.username')}</p>
      <p>
        <Link to="/login">{t('login.submit')}</Link>
      </p>
    </section>
  )
}
