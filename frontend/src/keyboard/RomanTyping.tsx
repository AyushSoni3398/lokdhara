import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { transliterate } from './transliterate'

/** Type in Roman letters with the phone's own keyboard, see the Devanagari, then add it. */
export function RomanTyping({ onAdd }: { onAdd: (text: string) => void }) {
  const { t } = useTranslation()
  const [roman, setRoman] = useState('')
  const devanagari = transliterate(roman)

  const add = () => {
    if (!roman.trim()) return
    onAdd(`${devanagari} `)
    setRoman('')
  }

  return (
    <div className="step">
      <label>
        {t('keyboard.romanLabel')}
        <input
          value={roman}
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          onChange={(e) => setRoman(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              add()
            }
          }}
        />
      </label>
      <p className="user-text" lang="hi" aria-live="polite">
        {devanagari || ' '}
      </p>
      <button type="button" className="small-action" disabled={!roman.trim()} onClick={add}>
        {t('keyboard.romanAdd')}
      </button>
      <p className="note">{t('keyboard.romanHint')}</p>
    </div>
  )
}
