import { useTranslation } from 'react-i18next'

import type { EntryType, Script } from '../../api/types'
import { Choice } from '../../components/Choice'
import type { Draft, DraftText } from '../../drafts/types'
import { KeyboardTextarea } from '../../keyboard/KeyboardTextarea'
import { ScriptWarning } from '../../text/ScriptWarning'

const SCRIPTS: Script[] = ['Deva', 'Latn', 'Nagm', 'Zyyy']
const ENTRY_TYPES: EntryType[] = ['word', 'phrase', 'sentence', 'paragraph', 'long_text']
const TRANSLATIONS = [
  { languageTag: 'hi', scriptCode: 'Deva' as const },
  { languageTag: 'en', scriptCode: 'Latn' as const },
]
export const MAIN_KEY = 'main'

/** The Mundari text (typed text or transcription) the translations translate. */
export function mainText(draft: Draft): DraftText | undefined {
  return draft.texts.find((text) => text.key === MAIN_KEY)
}

/** Drops empty optional text, and translations of text that is no longer there. */
export function filledTexts(texts: DraftText[]): DraftText[] {
  const filled = texts.filter((text) => text.content.trim())
  const keys = new Set(filled.map((text) => text.key))
  return filled.filter((text) => !text.translatesKey || keys.has(text.translatesKey))
}

export function textIsComplete(draft: Draft): boolean {
  const main = mainText(draft)
  const needsMain = draft.kind === 'text' || draft.kind === 'audio_text'
  return !needsMain || !!main?.content.trim()
}

/**
 * Text kept exactly as typed; nothing is corrected (docs/TEXT_PROCESSING_PIPELINE.md §0).
 * For audio this is an optional transcription; translations into Hindi and English are optional.
 */
export function TextStep({
  draft,
  onChange,
}: {
  draft: Draft
  onChange: (texts: DraftText[]) => void
}) {
  const { t } = useTranslation()
  const main = mainText(draft)
  const isTranscription = draft.kind !== 'text'

  const setMain = (changes: Partial<DraftText>) => {
    const base: DraftText = main ?? {
      key: MAIN_KEY,
      layerType: isTranscription ? 'transcription' : 'standalone',
      entryType: isTranscription ? undefined : 'sentence',
      languageTag: 'unr',
      scriptCode: 'Deva',
      content: '',
    }
    const updated = { ...base, ...changes }
    onChange([updated, ...draft.texts.filter((text) => text.key !== MAIN_KEY)])
  }

  const setTranslation = (languageTag: string, scriptCode: Script, content: string) => {
    const key = `translation-${languageTag}`
    const others = draft.texts.filter((text) => text.key !== key)
    if (!content.trim()) return onChange(others)
    onChange([
      ...others,
      { key, layerType: 'translation', languageTag, scriptCode, content, translatesKey: MAIN_KEY },
    ])
  }

  return (
    <div className="step">
      <p className="note">{t(isTranscription ? 'text.transcriptionHint' : 'text.hint')}</p>
      {!isTranscription && (
        <Choice
          name="entry-type"
          legend={t('text.entryType')}
          options={ENTRY_TYPES.map((value) => ({ value, label: t(`entryTypes.${value}`) }))}
          value={main?.entryType ?? 'sentence'}
          onChange={(entryType) => setMain({ entryType })}
        />
      )}
      <Choice
        name="script"
        legend={t('text.script')}
        options={SCRIPTS.map((value) => ({ value, label: t(`scripts.${value}`) }))}
        value={main?.scriptCode ?? 'Deva'}
        onChange={(scriptCode) => setMain({ scriptCode })}
      />
      <label>
        {t(isTranscription ? 'text.transcription' : 'text.mundari')}
        <KeyboardTextarea
          rows={5}
          lang="unr"
          spellCheck={false}
          value={main?.content ?? ''}
          onValue={(content) => setMain({ content })}
          keyboard={(main?.scriptCode ?? 'Deva') === 'Deva'}
        />
      </label>
      <ScriptWarning text={main?.content ?? ''} script={main?.scriptCode ?? 'Deva'} />
      {main?.content.trim() &&
        TRANSLATIONS.map(({ languageTag, scriptCode }) => (
          <label key={languageTag}>
            {t(`text.translation.${languageTag}`)}
            <KeyboardTextarea
              rows={3}
              lang={languageTag}
              value={draft.texts.find((x) => x.key === `translation-${languageTag}`)?.content ?? ''}
              onValue={(content) => setTranslation(languageTag, scriptCode, content)}
              keyboard={scriptCode === 'Deva'}
            />
          </label>
        ))}
    </div>
  )
}
