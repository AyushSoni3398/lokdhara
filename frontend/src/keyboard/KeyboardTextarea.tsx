import {
  type ReactNode,
  type TextareaHTMLAttributes,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from 'react'
import { useTranslation } from 'react-i18next'

import type { Script } from '../api/types'
import {
  DEVANAGARI,
  deleteBack,
  insertAt,
  type Keyboard,
  keyLabel,
  keyName,
  NAG_MUNDARI,
} from './layout'
import { RomanTyping } from './RomanTyping'

/** The scripts with an on-screen keyboard, and the language tag their keys are drawn in. */
const KEYBOARDS: Partial<Record<Script, { layout: Keyboard; lang: string }>> = {
  Deva: { layout: DEVANAGARI, lang: 'hi' },
  Nagm: { layout: NAG_MUNDARI, lang: 'unr-Nagm' },
}

/**
 * A text box with an on-screen keyboard for its script (Devanagari or Mundari Bani), for phones
 * without one installed. While it is open the phone's own keyboard stays closed (inputMode "none").
 */
export function KeyboardTextarea({
  label,
  value,
  onValue,
  script,
  ...props
}: Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'value' | 'onChange'> & {
  label: ReactNode
  value: string
  onValue: (value: string) => void
  /** The script typed; without a keyboard for it this is a plain text box. */
  script: Script
}) {
  const { t } = useTranslation()
  const id = useId()
  const box = useRef<HTMLTextAreaElement>(null)
  const cursor = useRef<number | null>(null)
  const [open, setOpen] = useState(false)
  const [roman, setRoman] = useState(false)
  const keyboard = KEYBOARDS[script]

  useLayoutEffect(() => {
    if (cursor.current === null || !box.current) return
    box.current.setSelectionRange(cursor.current, cursor.current)
    cursor.current = null
  }, [value])

  const edit = (
    change: (text: string, start: number, end: number) => { text: string; cursor: number },
  ) => {
    const el = box.current
    const start = el?.selectionStart ?? value.length
    const end = el?.selectionEnd ?? value.length
    const next = change(value, start, end)
    cursor.current = next.cursor
    onValue(next.text)
  }

  return (
    // The keyboard sits next to the label, not inside it: a label may hold only one control.
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <textarea
        {...props}
        id={id}
        ref={box}
        value={value}
        inputMode={open ? 'none' : undefined}
        onChange={(e) => onValue(e.target.value)}
      />
      {keyboard && (
        <button
          type="button"
          className="small-action"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          {t(open ? 'keyboard.close' : `keyboard.open.${script}`)}
        </button>
      )}
      {keyboard && open && (
        <div className="keyboard" role="group" aria-label={t(`keyboard.label.${script}`)}>
          {roman && script === 'Deva' && (
            <RomanTyping onAdd={(text) => edit((value, s, e) => insertAt(value, s, e, text))} />
          )}
          <div
            className="keyboard-keys"
            style={{
              gridTemplateColumns: `repeat(${keyboard.layout.columns}, 1fr)`,
            }}
          >
            {keyboard.layout.rows.flat().map((key) => (
              <button
                key={key}
                type="button"
                className="key"
                lang={keyboard.lang}
                aria-label={keyName(key)}
                // Keep the text box's cursor where it is.
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => edit((text, s, e) => insertAt(text, s, e, key))}
              >
                {keyLabel(key)}
              </button>
            ))}
          </div>
          <div className="keyboard-keys keyboard-bottom">
            {script === 'Deva' && (
              <button
                type="button"
                className="key action"
                aria-pressed={roman}
                onClick={() => setRoman(!roman)}
              >
                {t('keyboard.roman')}
              </button>
            )}
            <button
              type="button"
              className="key space"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => edit((text, s, e) => insertAt(text, s, e, ' '))}
            >
              {t('keyboard.space')}
            </button>
            <button
              type="button"
              className="key action newline"
              aria-label={t('keyboard.newLine')}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => edit((text, s, e) => insertAt(text, s, e, '\n'))}
            >
              ↵
            </button>
            <button
              type="button"
              className="key action delete"
              aria-label={t('keyboard.delete')}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => edit(deleteBack)}
            >
              ⌫
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
