import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError } from '../../api/client'
import * as api from '../../api/endpoints'
import type { Script, TextLayerCreate, TextLayerDetail } from '../../api/types'
import { Choice } from '../../components/Choice'
import { ErrorMessage } from '../../components/ErrorMessage'
import { KeyboardTextarea } from '../../keyboard/KeyboardTextarea'
import { ScriptWarning } from '../../text/ScriptWarning'

const SCRIPTS: Script[] = ['Deva', 'Latn', 'Nagm', 'Zyyy']
export const TRANSLATIONS = [
  { languageTag: 'hi', scriptCode: 'Deva' as const },
  { languageTag: 'en', scriptCode: 'Latn' as const },
]

/**
 * Saves a corrected version of a text. The server keeps every earlier version, and refuses the
 * save when someone saved a newer version in the meantime (`revision_conflict`).
 */
export function EditText({
  layer,
  onSaved,
  onCancel,
  onConflict,
}: {
  layer: TextLayerDetail
  onSaved: (layer: TextLayerDetail) => void
  onCancel: () => void
  onConflict: () => void
}) {
  const { t } = useTranslation()
  const revision = layer.current_revision
  const [content, setContent] = useState(revision?.content ?? '')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const unchanged = content === (revision?.content ?? '') || !content.trim()

  const save = async () => {
    if (!revision) return
    setBusy(true)
    setError(null)
    try {
      onSaved(
        await api.addRevision(layer.id, {
          base_revision_id: revision.id,
          content,
          change_note: note.trim() || undefined,
        }),
      )
    } catch (caught) {
      setError(caught)
      if (caught instanceof ApiError && caught.code === 'revision_conflict') onConflict()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="step">
      <KeyboardTextarea
        label={t('submission.edit.text')}
        rows={5}
        lang={layer.language_tag}
        spellCheck={false}
        value={content}
        onValue={setContent}
        keyboard={layer.script_code === 'Deva'}
      />
      <ScriptWarning text={content} script={layer.script_code} canChoose={false} />
      <label>
        {t('submission.edit.note')}
        <input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
      </label>
      <ErrorMessage error={error} />
      <div className="row">
        <button
          type="button"
          className="small-action"
          disabled={busy || unchanged}
          onClick={() => void save()}
        >
          {t('submission.edit.save')}
        </button>
        <button type="button" className="small-action" disabled={busy} onClick={onCancel}>
          {t('submission.edit.cancel')}
        </button>
      </div>
    </div>
  )
}

/** Adds a text that was left out when the submission was sent: a transcription or a translation. */
export function AddText({
  submissionId,
  base,
  label,
  chooseScript,
  onAdded,
  onCancel,
}: {
  submissionId: string
  base: Omit<TextLayerCreate, 'content' | 'script_code'> & { script_code?: Script }
  label: string
  chooseScript: boolean
  onAdded: () => void
  onCancel: () => void
}) {
  const { t } = useTranslation()
  const [content, setContent] = useState('')
  const [script, setScript] = useState<Script>(base.script_code ?? 'Deva')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const add = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.createTextLayer(submissionId, { ...base, script_code: script, content })
      onAdded()
    } catch (caught) {
      setError(caught)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="step">
      {chooseScript && (
        <Choice
          name={`script-${base.language_tag}`}
          legend={t('text.script')}
          options={SCRIPTS.map((value) => ({ value, label: t(`scripts.${value}`) }))}
          value={script}
          onChange={setScript}
        />
      )}
      <KeyboardTextarea
        label={label}
        rows={4}
        lang={base.language_tag}
        spellCheck={false}
        value={content}
        onValue={setContent}
        keyboard={script === 'Deva'}
      />
      <ScriptWarning text={content} script={script} canChoose={chooseScript} />
      <ErrorMessage error={error} />
      <div className="row">
        <button
          type="button"
          className="small-action"
          disabled={busy || !content.trim()}
          onClick={() => void add()}
        >
          {t('submission.edit.save')}
        </button>
        <button type="button" className="small-action" disabled={busy} onClick={onCancel}>
          {t('submission.edit.cancel')}
        </button>
      </div>
    </div>
  )
}
