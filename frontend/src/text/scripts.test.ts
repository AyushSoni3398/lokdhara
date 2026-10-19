import { describe, expect, it } from 'vitest'

import { scriptMismatch } from './scripts'

describe('scriptMismatch', () => {
  it('warns when no letter is in the chosen script', () => {
    expect(scriptMismatch('hoyo', 'Deva')).toBe(true)
    expect(scriptMismatch('होयो', 'Latn')).toBe(true)
    expect(scriptMismatch('होयो', 'Nagm')).toBe(true)
  })

  it('accepts the chosen script, also mixed with others', () => {
    expect(scriptMismatch('होयो', 'Deva')).toBe(false)
    expect(scriptMismatch('होयो school', 'Deva')).toBe(false)
    expect(scriptMismatch('\u{1E4D0}\u{1E4D1}', 'Nagm')).toBe(false)
  })

  it('never warns for mixed scripts, empty text or text without letters', () => {
    expect(scriptMismatch('hoyo', 'Zyyy')).toBe(false)
    expect(scriptMismatch('', 'Deva')).toBe(false)
    expect(scriptMismatch('123 , ?', 'Deva')).toBe(false)
  })

  it('ignores markup tags but reads wrapped words', () => {
    expect(scriptMismatch('होयो [inaudible]', 'Deva')).toBe(false)
    expect(scriptMismatch('[?hoyo]', 'Deva')).toBe(true)
  })
})
