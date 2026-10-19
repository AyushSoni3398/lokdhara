import { type TextareaHTMLAttributes, useLayoutEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { deleteBack, insertAt, KEY_ROWS, keyLabel } from './layout'

type Page = keyof typeof KEY_ROWS

/**
 * A text box with an optional on-screen Devanagari keyboard, for phones without a Hindi keyboard
 * installed. While it is open the phone's own keyboard stays closed (inputMode "none").
 */
export function KeyboardTextarea({
  value,
  onValue,
  keyboard = true,
  ...props
}: Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'value' | 'onChange'> & {
  value: string
  onValue: (value: string) => void
  /** Offer the keyboard (for Devanagari text); otherwise this is a plain text box. */
  keyboard?: boolean
}) {
  const { t } = useTranslation()
  const box = useRef<HTMLTextAreaElement>(null)
  const cursor = useRef<number | null>(null)
  const [open, setOpen] = useState(false)
  const [page, setPage] = useState<Page>('letters')

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
    <>
      <textarea
        {...props}
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
          {t(open ? 'keyboard.close' : 'keyboard.open')}
        </button>
      )}
      {keyboard && open && (
        <div className="keyboard" role="group" aria-label={t('keyboard.label')}>
          <div className="row">
            {(Object.keys(KEY_ROWS) as Page[]).map((name) => (
              <button
                key={name}
                type="button"
                className="small-action"
                aria-pressed={page === name}
                onClick={() => setPage(name)}
              >
                {t(`keyboard.${name}`)}
              </button>
            ))}
          </div>
          {KEY_ROWS[page].map((row, i) => (
            <div className="keyboard-row" key={i}>
              {row.map((key) => (
                <button
                  key={key}
                  type="button"
                  className="key"
                  lang="hi"
                  // Keep the text box's cursor where it is.
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => edit((text, s, e) => insertAt(text, s, e, key))}
                >
                  {keyLabel(key)}
                </button>
              ))}
            </div>
          ))}
          <div className="keyboard-row">
            <button
              type="button"
              className="key wide"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => edit((text, s, e) => insertAt(text, s, e, ' '))}
            >
              {t('keyboard.space')}
            </button>
            <button
              type="button"
              className="key"
              aria-label={t('keyboard.delete')}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => edit(deleteBack)}
            >
              ⌫
            </button>
          </div>
        </div>
      )}
    </>
  )
}
