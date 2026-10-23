import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams } from 'react-router'

import * as api from '../api/endpoints'
import { useSession } from '../auth/session'
import type { Kind, Prompt, RecordingMode, Speaker } from '../api/types'
import { Choice } from '../components/Choice'
import { ErrorMessage } from '../components/ErrorMessage'
import { useDrafts } from '../drafts/DraftsProvider'
import { useDraftStore } from '../drafts/store'
import { emptyDetails, type Draft, type DraftAudio } from '../drafts/types'
import { AudioCapture } from '../recording/AudioCapture'
import { DetailsStep } from './submission/DetailsStep'
import { PromptCard, PromptStep } from './submission/PromptStep'
import { filledTexts, TextStep, textIsComplete } from './submission/TextStep'

type Step = 'kind' | 'mode' | 'prompt' | 'audio' | 'text' | 'details' | 'review'

function stepsFor(draft: Draft): Step[] {
  const audio = draft.kind !== 'text'
  const prompted = draft.recordingMode === 'prompted' || draft.recordingMode === 'read'
  return [
    'kind',
    ...(audio ? (['mode'] as const) : []),
    ...(audio && prompted ? (['prompt'] as const) : []),
    ...(audio ? (['audio'] as const) : []),
    // Read speech is transcribed by the sentence that was read (docs/RECORDING_MODES.md §1).
    ...(draft.recordingMode === 'read' ? [] : (['text'] as const)),
    'details',
    'review',
  ]
}

function stepDone(step: Step, draft: Draft): boolean {
  switch (step) {
    case 'mode':
      return !!draft.recordingMode
    case 'prompt':
      return !!draft.promptId
    case 'audio':
      return !!draft.audio
    case 'text':
      return textIsComplete(draft)
    default:
      return true
  }
}

/** Dialect and area start from the speaker's profile, so they are not typed every time. */
function newDraft(ownerId: string, speaker: Speaker): Draft {
  const now = new Date().toISOString()
  return {
    clientSubmissionId: crypto.randomUUID(),
    ownerId,
    speakerId: speaker.id,
    speakerCode: speaker.speaker_code,
    collectionMethod: speaker.is_self ? 'self_recorded' : 'facilitator_field',
    kind: 'audio',
    texts: [],
    details: {
      ...emptyDetails(),
      dialectLabel: speaker.dialect_label ?? '',
      regionCoarse: speaker.region_coarse ?? '',
    },
    uploadKey: crypto.randomUUID(),
    ready: false,
    progress: {},
    createdAt: now,
    updatedAt: now,
  }
}

/** The contribution flow (docs/USER_FLOWS.md F1). Saved on the device at every step. */
export function NewSubmissionPage() {
  const { t } = useTranslation()
  const { speakerId, draftId } = useParams()
  const navigate = useNavigate()
  const store = useDraftStore()
  const userId = useSession().user.id
  const { refresh, uploadNow } = useDrafts()
  const [draft, setDraft] = useState<Draft | null>(null)
  const [step, setStep] = useState<Step>('kind')
  const [prompt, setPrompt] = useState<Prompt | null>(null)
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    if (draftId) {
      store.get(draftId).then((saved) => {
        if (!saved || saved.ownerId !== userId) return setError('draft_not_found')
        setDraft(saved)
        setStep('review')
      }, setError)
    } else if (speakerId) {
      api
        .getSpeaker(speakerId)
        .then((speaker) => setDraft(newDraft(userId, speaker)), setError)
    }
  }, [draftId, speakerId, store, userId])

  const save = useCallback(
    async (next: Draft) => {
      await store.put({ ...next, updatedAt: new Date().toISOString() })
      await refresh()
    },
    [store, refresh],
  )

  const choosePrompt = useCallback((chosen: Prompt | null) => {
    setPrompt(chosen)
    setDraft(
      (current) =>
        current && { ...current, promptId: chosen?.id, promptText: chosen?.text ?? undefined },
    )
  }, [])

  if (!draft) return <ErrorMessage error={error} />

  const steps = stepsFor(draft)
  const index = steps.indexOf(step)
  const update = (changes: Partial<Draft>) => setDraft({ ...draft, ...changes })
  const go = async (to: Step) => {
    await save(draft) // kept on the device at every step, the recording included
    setStep(to)
    window.scrollTo?.(0, 0)
  }

  const finish = async (ready: boolean) => {
    const final = { ...draft, texts: filledTexts(draft.texts), ready, lastError: undefined }
    await save(final)
    if (ready) uploadNow()
    void navigate('/submissions')
  }

  return (
    <section>
      <p className="note">
        {t('wizard.speaker', { code: draft.speakerCode })} ·{' '}
        {t('wizard.progress', { step: index + 1, total: steps.length })}
      </p>
      <h1>{t(`wizard.steps.${step}`)}</h1>

      {step === 'kind' && (
        <Choice
          name="kind"
          legend={t('wizard.kindLegend')}
          options={(['audio', 'text', 'audio_text'] as Kind[]).map((value) => ({
            value,
            label: t(`kinds.${value}`),
          }))}
          value={draft.kind}
          onChange={(kind) =>
            update(
              kind === 'text'
                ? {
                    kind,
                    recordingMode: undefined,
                    promptId: undefined,
                    audio: undefined,
                    texts: [],
                  }
                : { kind, texts: [] },
            )
          }
        />
      )}

      {step === 'mode' && (
        <Choice
          name="mode"
          legend={t('wizard.modeLegend')}
          options={(['free', 'prompted', 'read'] as RecordingMode[]).map((value) => ({
            value,
            label: t(`modes.${value}.label`),
            hint: t(`modes.${value}.hint`),
          }))}
          value={draft.recordingMode}
          onChange={(recordingMode) => {
            setPrompt(null)
            // Read speech is audio only: the sentence read is its text.
            const kind = recordingMode === 'read' ? 'audio' : draft.kind
            update({ recordingMode, kind, promptId: undefined, promptText: undefined, texts: [] })
          }}
        />
      )}

      {step === 'prompt' &&
        (draft.recordingMode === 'prompted' || draft.recordingMode === 'read') && (
          <PromptStep mode={draft.recordingMode} chosen={prompt} onChoose={choosePrompt} />
        )}

      {step === 'audio' && (
        <>
          {prompt ? (
            <PromptCard prompt={prompt} />
          ) : (
            draft.promptText && <p className="prompt-card">{draft.promptText}</p>
          )}
          <AudioCapture value={draft.audio} onChange={(audio) => update({ audio })} />
        </>
      )}

      {step === 'text' && <TextStep draft={draft} onChange={(texts) => update({ texts })} />}

      {step === 'details' && (
        <DetailsStep
          details={draft.details}
          hasAudio={draft.kind !== 'text'}
          onChange={(details) => update({ details })}
        />
      )}

      {step === 'review' && <Review draft={draft} />}

      <ErrorMessage error={error} />
      <div className="wizard-nav">
        {index > 0 && (
          <button type="button" className="action" onClick={() => void go(steps[index - 1]!)}>
            {t('wizard.back')}
          </button>
        )}
        {step !== 'review' ? (
          <button
            type="button"
            className="action primary"
            disabled={!stepDone(step, draft)}
            onClick={() => void go(steps[index + 1]!)}
          >
            {t('wizard.next')}
          </button>
        ) : (
          <>
            <button type="button" className="action primary" onClick={() => void finish(true)}>
              {t('wizard.saveAndUpload')}
            </button>
            <button type="button" className="action" onClick={() => void finish(false)}>
              {t('wizard.saveForLater')}
            </button>
          </>
        )}
      </div>
      <p className="note">
        <Link to="/submissions">{t('wizard.leave')}</Link>
      </p>
    </section>
  )
}

function Review({ draft }: { draft: Draft }) {
  const { t } = useTranslation()
  const texts = filledTexts(draft.texts)
  return (
    <dl className="summary">
      <dt>{t('review.kind')}</dt>
      <dd>{t(`kinds.${draft.kind}`)}</dd>
      {draft.recordingMode && (
        <>
          <dt>{t('review.mode')}</dt>
          <dd>{t(`modes.${draft.recordingMode}.label`)}</dd>
        </>
      )}
      {draft.promptText && (
        <>
          <dt>{t('review.prompt')}</dt>
          <dd>{draft.promptText}</dd>
        </>
      )}
      {draft.audio && (
        <>
          <dt>{t('review.audio')}</dt>
          <dd>
            {t(`review.audioSource.${draft.audio.source}`)}
            <DraftPlayer audio={draft.audio} />
          </dd>
        </>
      )}
      {texts.map((text) => (
        <Fragment key={text.key}>
          <dt>{t(`review.text.${text.layerType}`, { language: text.languageTag })}</dt>
          <dd className="user-text">{text.content}</dd>
        </Fragment>
      ))}
      <dt>{t('details.contentType')}</dt>
      <dd>{t(`contentTypes.${draft.details.contentType}`)}</dd>
      {draft.details.title && (
        <>
          <dt>{t('details.title')}</dt>
          <dd className="user-text">{draft.details.title}</dd>
        </>
      )}
    </dl>
  )
}

/** The recording as it is on the phone, to listen to once more before sending it. */
function DraftPlayer({ audio }: { audio: DraftAudio }) {
  const { t } = useTranslation()
  const url = useMemo(() => URL.createObjectURL(audio.blob), [audio])
  useEffect(() => () => URL.revokeObjectURL(url), [url])
  return (
    <div className="captured">
      <audio controls src={url} aria-label={t('record.listen')} />
    </div>
  )
}
