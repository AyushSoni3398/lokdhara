import { useTranslation } from 'react-i18next'
import { Link, Outlet, useNavigate } from 'react-router'

import { useAuth } from '../auth/session'
import { LanguageSwitcher } from './LanguageSwitcher'

export function Layout() {
  const { t } = useTranslation()
  const { state, signOut } = useAuth()
  const navigate = useNavigate()
  // Home first, then sign out: whoever signs in next starts at home, not on the page the last
  // person had open (it may be their own speaker or item, which the next person cannot see).
  const leave = async () => {
    await navigate('/', { replace: true })
    await signOut()
  }
  return (
    <div className="layout">
      <header className="header">
        <Link to="/" className="brand">
          {t('app.name')}
        </Link>
        <div className="header-tools">
          <LanguageSwitcher />
          {state.status === 'signedIn' && (
            <button type="button" className="link-button" onClick={() => void leave()}>
              {t('nav.signOut')}
            </button>
          )}
        </div>
      </header>
      <main className="main">
        <Outlet />
      </main>
    </div>
  )
}
