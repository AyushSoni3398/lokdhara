import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router'

import * as api from '../api/endpoints'
import type {
  ContentType,
  Kind,
  Release,
  ReleaseCheck,
  ReleasePreview,
  ReleasePurpose,
  SelectionCriteria,
} from '../api/types'
import { hasRole, useSession } from '../auth/session'
import { ErrorMessage } from '../components/ErrorMessage'
import { PURPOSES, releaseName } from './ReleasesPage'

const KINDS: Kind[] = ['audio', 'text', 'audio_text']
const CONTENT_TYPES: ContentType[] = [
  'story',
  'conversation',
  'vocabulary',
  'song',
  'sentence_list',
  'other',
]
const VERSION = /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/

function toggle<T>(values: T[], value: T): T[] {
  return values.includes(value) ? values.filter((v) => v !== value) : [...values, value]
}

/** One release: a draft is edited, previewed, checked and frozen; a frozen one is exported. */
export function ReleasePage() {
  const { t } = useTranslation()
  const { releaseId = '' } = useParams()
  const session = useSession()
  const allowed = hasRole(session, 'researcher', 'admin')
  const [release, setRelease] = useState<Release | null>(null)
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    if (allowed) api.getRelease(releaseId).then(setRelease, setError)
  }, [allowed, releaseId])

  if (!allowed) return <p className="note">{t('catalogue.notAllowed')}</p>

  return (
    <section>
      <p>
        <Link to="/datasets">{t('releases.back')}</Link>
      </p>
      <ErrorMessage error={error} />
      {release && (
        <>
          <h1>{releaseName(release)}</h1>
          <p className="note">
            {t(`releases.status.${release.status}`)} · {t(`releases.purposes.${release.purpose}`)}
          </p>
          {release.status === 'draft' ? (
            <Draft key={release.updated_at} release={release} onChange={setRelease} />
          ) : (
            <Frozen release={release} onChange={setRelease} />
          )}
        </>
      )}
    </section>
  )
}

function Draft({ release, onChange }: { release: Release; onChange: (r: Release) => void }) {
  const { t } = useTranslation()
  const isAdmin = hasRole(useSession(), 'admin')
  const [purpose, setPurpose] = useState<ReleasePurpose>(release.purpose)
  const [criteria, setCriteria] = useState<SelectionCriteria>(release.selection_criteria)
  const [licence, setLicence] = useState(release.licence ?? '')
  const [dataCard, setDataCard] = useState(release.data_card_markdown)
  const [preview, setPreview] = useState<ReleasePreview | null>(null)
  const [checks, setChecks] = useState<ReleaseCheck[] | null>(null)
  const [version, setVersion] = useState('0.1.0')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    api.previewRelease(release.id).then(setPreview, setError)
  }, [release.id, release.updated_at])

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
  const save = () =>
    run(async () => {
      onChange(
        await api.updateRelease(release.id, {
          purpose,
          selection_criteria: criteria,
          licence: licence.trim() || null,
          data_card_markdown: dataCard,
        }),
      )
    })
  const check = () =>
    run(async () => {
      setChecks((await api.checkRelease(release.id)).checks)
    })
  const freeze = () =>
    run(async () => {
      onChange(await api.freezeRelease(release.id, version))
    })
  const seconds = Math.round((preview?.total_duration_ms ?? 0) / 1000)

  return (
    <>
      <form
        className="step"
        onSubmit={(event) => {
          event.preventDefault()
          void save()
        }}
      >
        <h2>{t('releases.selection')}</h2>
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
        <fieldset>
          <legend>{t('catalogue.kind')}</legend>
          {KINDS.map((kind) => (
            <label key={kind} className="inline">
              <input
                type="checkbox"
                checked={criteria.kinds.includes(kind)}
                onChange={() => setCriteria({ ...criteria, kinds: toggle(criteria.kinds, kind) })}
              />
              {t(`kinds.${kind}`)}
            </label>
          ))}
        </fieldset>
        <fieldset>
          <legend>{t('catalogue.contentType')}</legend>
          {CONTENT_TYPES.map((type) => (
            <label key={type} className="inline">
              <input
                type="checkbox"
                checked={criteria.content_types.includes(type)}
                onChange={() =>
                  setCriteria({ ...criteria, content_types: toggle(criteria.content_types, type) })
                }
              />
              {t(`contentTypes.${type}`)}
            </label>
          ))}
        </fieldset>
        <p className="note">{t('releases.anyHint')}</p>
        <label className="inline">
          <input
            type="checkbox"
            checked={criteria.needs_audio}
            onChange={(e) => setCriteria({ ...criteria, needs_audio: e.target.checked })}
          />
          {t('releases.needsAudio')}
        </label>
        <label className="inline">
          <input
            type="checkbox"
            checked={criteria.needs_transcription}
            onChange={(e) => setCriteria({ ...criteria, needs_transcription: e.target.checked })}
          />
          {t('releases.needsTranscription')}
        </label>
        <label>
          {t('releases.licence')}
          <input value={licence} maxLength={200} onChange={(e) => setLicence(e.target.value)} />
        </label>
        <label>
          {t('releases.dataCard')}
          <textarea
            rows={5}
            maxLength={50000}
            value={dataCard}
            onChange={(e) => setDataCard(e.target.value)}
          />
        </label>
        <button type="submit" className="small-action" disabled={busy}>
          {t('releases.save')}
        </button>
      </form>

      {preview && (
        <div className="step">
          <h2>{t('releases.preview')}</h2>
          <p>
            {t('releases.items', { count: preview.item_count })} ·{' '}
            {t('catalogue.seconds', { count: seconds })}
          </p>
          <p className="note">{t('releases.leftOut', { count: preview.left_out_count })}</p>
          <ul>
            {Object.entries(preview.by_content_type).map(([type, count]) => (
              <li key={type}>
                {t(`contentTypes.${type}`)}: {count}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="step">
        <h2>{t('releases.checks')}</h2>
        <p className="note">{t('releases.checksIntro')}</p>
        <button type="button" className="small-action" disabled={busy} onClick={() => void check()}>
          {t('releases.runChecks')}
        </button>
        {checks && (
          <ul className="checks">
            {checks.map((c) => (
              <li key={c.code}>
                <span aria-hidden="true">{c.passed ? '✅' : c.blocking ? '❌' : '⚠️'}</span>{' '}
                <strong>{c.code}</strong> {c.message}
              </li>
            ))}
          </ul>
        )}
      </div>

      {isAdmin && (
        <form
          className="step"
          onSubmit={(event) => {
            event.preventDefault()
            void freeze()
          }}
        >
          <h2>{t('releases.freeze')}</h2>
          <p className="note">{t('releases.freezeIntro')}</p>
          <label>
            {t('releases.version')}
            <input value={version} maxLength={30} onChange={(e) => setVersion(e.target.value)} />
          </label>
          <button type="submit" className="small-action" disabled={busy || !VERSION.test(version)}>
            {t('releases.freezeButton')}
          </button>
        </form>
      )}
      <ErrorMessage error={error} />
    </>
  )
}

function Frozen({ release, onChange }: { release: Release; onChange: (r: Release) => void }) {
  const { t, i18n } = useTranslation()
  const isAdmin = hasRole(useSession(), 'admin')
  const [purposeStatement, setPurposeStatement] = useState('')
  const [note, setNote] = useState('')
  const [requested, setRequested] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const date = (iso: string) => new Date(iso).toLocaleDateString(i18n.resolvedLanguage)

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

  return (
    <>
      <p>{t('releases.frozenOn', { date: date(release.frozen_at ?? release.created_at) })}</p>
      <p className="note">
        {t('releases.manifest')} <code>{release.manifest_sha256}</code>
      </p>
      {release.status === 'retracted' ? (
        <div className="problem">
          <p>
            {t('releases.retractedOn', { date: date(release.retracted_at ?? release.updated_at) })}
          </p>
          <p className="user-text">{release.retraction_note}</p>
        </div>
      ) : (
        <>
          <form
            className="step"
            onSubmit={(event) => {
              event.preventDefault()
              void run(async () => {
                await api.requestExport(release.id, purposeStatement.trim())
                setPurposeStatement('')
                setRequested(true)
              })
            }}
          >
            <h2>{t('exports.request')}</h2>
            <label>
              {t('exports.purposeStatement')}
              <textarea
                rows={3}
                maxLength={2000}
                value={purposeStatement}
                onChange={(e) => setPurposeStatement(e.target.value)}
              />
            </label>
            <button
              type="submit"
              className="small-action"
              disabled={busy || !purposeStatement.trim()}
            >
              {t('exports.send')}
            </button>
            {requested && (
              <p className="note" role="status">
                {t('exports.requested')} <Link to="/exports">{t('exports.link')}</Link>
              </p>
            )}
          </form>
          {isAdmin && (
            <form
              className="step"
              onSubmit={(event) => {
                event.preventDefault()
                void run(async () => onChange(await api.retractRelease(release.id, note.trim())))
              }}
            >
              <h2>{t('releases.retract')}</h2>
              <p className="note">{t('releases.retractIntro')}</p>
              <label>
                {t('reports.note')}
                <textarea
                  rows={2}
                  maxLength={2000}
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                />
              </label>
              <button type="submit" className="small-action" disabled={busy || !note.trim()}>
                {t('releases.retractButton')}
              </button>
            </form>
          )}
        </>
      )}
      <ErrorMessage error={error} />
    </>
  )
}
