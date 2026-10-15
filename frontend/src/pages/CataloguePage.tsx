import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

import * as api from '../api/endpoints'
import type { CatalogueItem, CatalogueQuery, ContentType, Kind } from '../api/types'
import { hasRole, useSession } from '../auth/session'
import { ErrorMessage } from '../components/ErrorMessage'

const KINDS: Kind[] = ['audio', 'text', 'audio_text']
const CONTENT_TYPES: ContentType[] = [
  'story',
  'conversation',
  'vocabulary',
  'song',
  'sentence_list',
  'other',
]

/**
 * Researchers search accepted items that consent allows for research; hidden items never
 * appear (ROADMAP M6). Contributors' text is always shown as unverified (ADR-021).
 */
export function CataloguePage() {
  const { t } = useTranslation()
  const session = useSession()
  const allowed = hasRole(session, 'researcher', 'admin')
  const [draft, setDraft] = useState<CatalogueQuery>({})
  const [query, setQuery] = useState<CatalogueQuery>({})
  const [items, setItems] = useState<CatalogueItem[] | null>(null)
  const [next, setNext] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    if (!allowed) return
    api.searchCatalogue(query).then((page) => {
      setItems(page.items)
      setNext(page.next_cursor)
    }, setError)
  }, [allowed, query])

  const more = async (cursor: string) => {
    setBusy(true)
    setError(null)
    try {
      const page = await api.searchCatalogue({ ...query, cursor })
      setItems((current) => [...(current ?? []), ...page.items])
      setNext(page.next_cursor)
    } catch (caught) {
      setError(caught)
    } finally {
      setBusy(false)
    }
  }

  if (!allowed) return <p className="note">{t('catalogue.notAllowed')}</p>

  return (
    <section>
      <h1>{t('catalogue.title')}</h1>
      <p className="note">{t('catalogue.intro')}</p>
      <form
        className="step"
        role="search"
        onSubmit={(event) => {
          event.preventDefault()
          setError(null)
          setQuery({ ...draft, q: draft.q?.trim() || undefined })
        }}
      >
        <label>
          {t('catalogue.search')}
          <input
            type="search"
            maxLength={200}
            value={draft.q ?? ''}
            onChange={(e) => setDraft({ ...draft, q: e.target.value })}
          />
        </label>
        <label>
          {t('catalogue.kind')}
          <select
            value={draft.kind ?? ''}
            onChange={(e) => setDraft({ ...draft, kind: (e.target.value || undefined) as Kind })}
          >
            <option value="">{t('catalogue.any')}</option>
            {KINDS.map((kind) => (
              <option key={kind} value={kind}>
                {t(`kinds.${kind}`)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t('catalogue.contentType')}
          <select
            value={draft.content_type ?? ''}
            onChange={(e) =>
              setDraft({ ...draft, content_type: (e.target.value || undefined) as ContentType })
            }
          >
            <option value="">{t('catalogue.any')}</option>
            {CONTENT_TYPES.map((type) => (
              <option key={type} value={type}>
                {t(`contentTypes.${type}`)}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" className="small-action" disabled={busy}>
          {t('catalogue.find')}
        </button>
      </form>
      <ErrorMessage error={error} />
      {items?.length === 0 && <p className="note">{t('catalogue.none')}</p>}
      <ul className="list">
        {items?.map((item) => (
          <CatalogueEntry key={item.id} item={item} />
        ))}
      </ul>
      {next && (
        <button
          type="button"
          className="small-action"
          disabled={busy}
          onClick={() => void more(next)}
        >
          {t('catalogue.more')}
        </button>
      )}
    </section>
  )
}

function CatalogueEntry({ item }: { item: CatalogueItem }) {
  const { t } = useTranslation()
  const seconds = item.duration_ms === null ? null : Math.round(item.duration_ms / 1000)
  const details = [
    t(`kinds.${item.kind}`),
    t(`contentTypes.${item.content_type}`),
    seconds === null ? null : t('catalogue.seconds', { count: seconds }),
    item.dialect_label,
  ].filter(Boolean)
  return (
    <li className="list-item">
      <Link to={`/submissions/${item.id}`}>
        <strong>{item.title || t(`kinds.${item.kind}`)}</strong>
      </Link>
      <span className="note">{details.join(' · ')}</span>
      {item.text_preview && (
        <p className="user-text" lang={item.language_tag}>
          {item.text_preview}
        </p>
      )}
      {item.text_preview && <span className="badge">{t('submission.unverified')}</span>}
      {item.restriction_flags.includes('culturally_restricted') && (
        <span className="status waiting">{t('restrictions.culturally_restricted')}</span>
      )}
      {item.quality_flags.length > 0 && (
        <span className="note">
          {t('catalogue.quality', {
            flags: item.quality_flags
              .map((flag) => t(`catalogue.qualityFlags.${flag}`, { defaultValue: flag }))
              .join(', '),
          })}
        </span>
      )}
    </li>
  )
}
