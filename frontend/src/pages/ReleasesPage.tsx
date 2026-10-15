import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router'

import * as api from '../api/endpoints'
import type { Release, ReleasePurpose } from '../api/types'
import { hasRole, useSession } from '../auth/session'
import { ErrorMessage } from '../components/ErrorMessage'

export const PURPOSES: ReleasePurpose[] = [
  'internal_research',
  'external_research',
  'public',
  'ai_training',
]
const SLUG = /^[a-z0-9]+(-[a-z0-9]+)*$/

export function releaseName(release: Pick<Release, 'slug' | 'version'>): string {
  return release.version ? `${release.slug}@${release.version}` : release.slug
}

/** Dataset releases: researchers start drafts, admins freeze them (ROADMAP M7). */
export function ReleasesPage() {
  const { t, i18n } = useTranslation()
  const session = useSession()
  const allowed = hasRole(session, 'researcher', 'admin')
  const navigate = useNavigate()
  const [releases, setReleases] = useState<Release[] | null>(null)
  const [slug, setSlug] = useState('')
  const [purpose, setPurpose] = useState<ReleasePurpose>('internal_research')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    if (allowed) api.listReleases().then(setReleases, setError)
  }, [allowed])

  if (!allowed) return <p className="note">{t('catalogue.notAllowed')}</p>

  const create = async () => {
    setBusy(true)
    setError(null)
    try {
      const release = await api.createRelease({ slug, purpose })
      void navigate(`/datasets/${release.id}`)
    } catch (caught) {
      setError(caught)
      setBusy(false)
    }
  }
  const date = (iso: string) => new Date(iso).toLocaleDateString(i18n.resolvedLanguage)

  return (
    <section>
      <h1>{t('releases.title')}</h1>
      <p className="note">{t('releases.intro')}</p>
      <p>
        <Link to="/exports">{t('exports.link')}</Link>
      </p>
      <ErrorMessage error={error} />
      {releases?.length === 0 && <p className="note">{t('releases.none')}</p>}
      <ul className="list">
        {releases?.map((release) => (
          <li key={release.id} className="list-item">
            <Link to={`/datasets/${release.id}`}>
              <strong>{releaseName(release)}</strong>
            </Link>
            <span className="note">
              {t(`releases.status.${release.status}`)} · {t(`releases.purposes.${release.purpose}`)}{' '}
              · {date(release.frozen_at ?? release.created_at)}
            </span>
          </li>
        ))}
      </ul>
      <form
        className="step"
        onSubmit={(event) => {
          event.preventDefault()
          void create()
        }}
      >
        <h2>{t('releases.new')}</h2>
        <label>
          {t('releases.slug')}
          <input
            value={slug}
            maxLength={60}
            placeholder="mundari-speech-pilot"
            onChange={(e) => setSlug(e.target.value.toLowerCase())}
          />
          <small>{t('releases.slugHint')}</small>
        </label>
        <label>
          {t('releases.purpose')}
          <select value={purpose} onChange={(e) => setPurpose(e.target.value as ReleasePurpose)}>
            {PURPOSES.map((value) => (
              <option key={value} value={value}>
                {t(`releases.purposes.${value}`)}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" className="small-action" disabled={busy || !SLUG.test(slug)}>
          {t('releases.start')}
        </button>
      </form>
    </section>
  )
}
