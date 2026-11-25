import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import * as api from '../../api/endpoints'
import type { Prompt, PromptType, Script } from '../../api/types'
import { Choice } from '../../components/Choice'
import { ErrorMessage } from '../../components/ErrorMessage'

export const READ_SCRIPTS: Script[] = ['Deva', 'Latn', 'Nagm']

/** Shows one approved prompt at a time; "show another" skips it (docs/RECORDING_MODES.md §1).
 * The server remembers what each person has been shown, so prompts do not come back on a
 * later visit either, until all of a kind have been seen (ADR-036). */
export function PromptStep({
  mode,
  chosen,
  onChoose,
}: {
  mode: 'prompted' | 'read'
  chosen: Prompt | null
  onChoose: (prompt: Prompt | null) => void
}) {
  const { t } = useTranslation()
  const [type, setType] = useState<PromptType | undefined>(
    mode === 'read' ? 'read_sentence' : undefined,
  )
  const [script, setScript] = useState<Script>('Deva')
  const [seen, setSeen] = useState<string[]>([])
  const [error, setError] = useState<unknown>(null)

  const load = useCallback(
    (promptType: PromptType, readScript: Script, exclude: string[]) => {
      api
        .nextPrompt(promptType, promptType === 'read_sentence' ? readScript : null, exclude)
        .then((prompt) => {
          setError(null)
          setSeen([...exclude, prompt.id])
          onChoose(prompt)
        })
        .catch((failure: unknown) => {
          onChoose(null)
          setError(failure)
        })
    },
    [onChoose],
  )

  // A first prompt whenever the type or script is chosen (both clear the current prompt).
  useEffect(() => {
    if (type && !chosen && !error) load(type, script, [])
  }, [type, script, chosen, error, load])

  return (
    <div className="step">
      {mode === 'prompted' && (
        <Choice
          name="prompt-type"
          legend={t('prompt.typeLegend')}
          options={[
            { value: 'image', label: t('prompt.image') },
            { value: 'situation', label: t('prompt.situation') },
          ]}
          value={type}
          onChange={(value) => {
            setError(null)
            onChoose(null)
            setType(value)
          }}
        />
      )}
      {mode === 'read' && (
        <Choice
          name="read-script"
          legend={t('prompt.scriptLegend')}
          options={READ_SCRIPTS.map((value) => ({ value, label: t(`scripts.${value}`) }))}
          value={script}
          onChange={(value) => {
            setError(null)
            onChoose(null)
            setScript(value)
          }}
        />
      )}
      {chosen?.started_again && (
        <p className="note" role="status">
          {t('prompt.startedAgain')}
        </p>
      )}
      {chosen && <PromptCard prompt={chosen} />}
      <ErrorMessage error={error} />
      {type && (
        <button type="button" className="action" onClick={() => load(type, script, seen)}>
          {t('prompt.another')}
        </button>
      )}
    </div>
  )
}

export function PromptCard({ prompt }: { prompt: Prompt }) {
  const { t, i18n } = useTranslation()
  // The meaning in the app's language, unless the prompt is already in it.
  const english = i18n.language.startsWith('en')
  const meaning = english ? prompt.translation_en : prompt.translation_hi
  const meaningTag = english ? 'en' : 'hi'
  return (
    <figure className="prompt-card">
      {prompt.image_url && <img src={prompt.image_url} alt={t('prompt.imageAlt')} />}
      {prompt.text && (
        <figcaption
          lang={prompt.text_language_tag ?? undefined}
          className={`script-${prompt.script_code ?? ''}`}
        >
          {prompt.text}
        </figcaption>
      )}
      {meaning && prompt.text_language_tag !== meaningTag && (
        <p className="prompt-meaning" lang={meaningTag}>
          {t('prompt.meaning')} {meaning}
        </p>
      )}
      {prompt.audio_url && (
        <audio controls src={prompt.audio_url} aria-label={t('prompt.listen')} />
      )}
    </figure>
  )
}
