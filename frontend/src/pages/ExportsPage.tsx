import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

import * as api from '../api/endpoints'
import type { ExportDownload, ExportRequest } from '../api/types'
import { hasRole, useSession } from '../auth/session'
import { ErrorMessage } from '../components/ErrorMessage'
import { releaseName } from './ReleasesPage'

/**
 * Export requests: researchers see their own and download ready packages; admins see all and
 * decide on other people's requests (ROADMAP M7).
 */
export function ExportsPage() {
  const { t } = useTranslation()
  const session = useSession()
  const allowed = hasRole(session, 'researcher', 'admin')
  const [items, setItems] = useState<ExportRequest[] | null>(null)
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    if (allowed) api.listExports().then(setItems, setError)
  }, [allowed])

  if (!allowed) return <p className="note">{t('catalogue.notAllowed')}</p>

  const replace = (changed: ExportRequest) =>
    setItems((current) => current?.map((item) => (item.id === changed.id ? changed : item)) ?? null)

  return (
    <section>
      <p>
        <Link to="/datasets">{t('releases.back')}</Link>
      </p>
      <h1>{t('exports.title')}</h1>
      <p className="note">{t('exports.intro')}</p>
      <ErrorMessage error={error} />
      {items?.length === 0 && <p className="note">{t('exports.none')}</p>}
      <ul className="list">
        {items?.map((item) => (
          <ExportCard key={item.id} item={item} onChange={replace} />
        ))}
      </ul>
    </section>
  )
}

function ExportCard({
  item,
  onChange,
}: {
  item: ExportRequest
  onChange: (item: ExportRequest) => void
}) {
  const { t, i18n } = useTranslation()
  const isAdmin = hasRole(useSession(), 'admin')
  const [note, setNote] = useState('')
  const [link, setLink] = useState<ExportDownload | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const date = (iso: string) => new Date(iso).toLocaleString(i18n.resolvedLanguage)

  const run = async (action: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (caught) {
      setError(caught)
    } finally {
      setBusy(false)
    }
  }
  const release = { slug: item.release_slug, version: item.release_version }

  return (
    <li className="list-item">
      <Link to={`/datasets/${item.release_id}`}>
        <strong>{releaseName(release)}</strong>
      </Link>
      <span className="note">
        {t(`exports.status.${item.status}`)} ·{' '}
        {item.mine ? t('exports.byYou') : t('exports.by', { name: item.requested_by_name })} ·{' '}
        {date(item.created_at)}
      </span>
      <p className="user-text">{item.purpose_statement}</p>
      {item.decision_note && (
        <p className="note">{t('exports.decisionNote', { note: item.decision_note })}</p>
      )}
      {item.status === 'ready' && item.expires_at && (
        <p className="note">
          {t('exports.expires', { date: date(item.expires_at) })} ·{' '}
          {t('exports.downloads', { count: item.download_count })}
        </p>
      )}

      {isAdmin && item.status === 'requested' && (
        <>
          <label>
            {t('reports.note')}
            <textarea
              rows={2}
              maxLength={2000}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </label>
          <div className="row">
            <button
              type="button"
              className="small-action"
              disabled={busy}
              onClick={() =>
                void run(async () =>
                  onChange(await api.approveExport(item.id, note.trim() || undefined)),
                )
              }
            >
              {t('exports.approve')}
            </button>
            <button
              type="button"
              className="small-action"
              disabled={busy || !note.trim()}
              onClick={() =>
                void run(async () => onChange(await api.rejectExport(item.id, note.trim())))
              }
            >
              {t('exports.reject')}
            </button>
          </div>
        </>
      )}

      {item.mine && item.status === 'ready' && !link && (
        <button
          type="button"
          className="small-action"
          disabled={busy}
          onClick={() =>
            void run(async () => {
              setLink(await api.downloadExport(item.id))
              onChange({ ...item, download_count: item.download_count + 1 })
            })
          }
        >
          {t('exports.getLink')}
        </button>
      )}
      {link && (
        <p>
          <a href={link.download_url} download={link.file_name}>
            {t('exports.save', { name: link.file_name })}
          </a>
          <br />
          <small className="note">
            {t('exports.checksum')} <code>{link.sha256}</code>
          </small>
        </p>
      )}
      <ErrorMessage error={error} />
    </li>
  )
}
