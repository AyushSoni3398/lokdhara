import { describe, expect, it } from 'vitest'

import { DEVANAGARI, deleteBack, insertAt, keyLabel, keyName, NAG_MUNDARI } from './layout'

describe('Devanagari keyboard', () => {
  it('builds syllables from letters and signs', () => {
    let state = insertAt('', 0, 0, 'क')
    state = insertAt(state.text, state.cursor, state.cursor, 'ि')
    expect(state).toEqual({ text: 'कि', cursor: 2 })
  })

  it('types in the middle and replaces a selection', () => {
    expect(insertAt('कल', 1, 1, 'ा')).toEqual({ text: 'काल', cursor: 2 })
    expect(insertAt('कमल', 1, 2, 'ि')).toEqual({ text: 'किल', cursor: 2 })
  })

  it('deletes one sign at a time, or the selection', () => {
    expect(deleteBack('कि', 2, 2)).toEqual({ text: 'क', cursor: 1 })
    expect(deleteBack('कमल', 0, 2)).toEqual({ text: 'ल', cursor: 0 })
    expect(deleteBack('क', 0, 0)).toEqual({ text: 'क', cursor: 0 })
  })

  it('shows signs on a dotted circle', () => {
    expect(keyLabel('ि')).toBe('◌ि')
    expect(keyLabel('क')).toBe('क')
  })
})

describe('Mundari Bani keyboard', () => {
  it('has all 42 letters, signs and digits of the script', () => {
    const keys = NAG_MUNDARI.rows.flat().filter((key) => /\p{Script=Nag_Mundari}/u.test(key))
    expect(keys).toHaveLength(42)
  })

  it('shows signs alone and names every key', () => {
    expect(keyLabel('\u{1E4EC}')).toBe('\u{1E4EC}')
    expect(keyName('\u{1E4D0}')).toBe('o')
    expect(keyName('\u{1E4EC}')).toBe('muhor sign')
    expect(keyName('\u{1E4F9}')).toBe('9')
    expect(keyName('क')).toBeUndefined()
  })

  it('deletes one letter, not half of one', () => {
    expect(deleteBack('\u{1E4D5}\u{1E4D6}', 4, 4)).toEqual({ text: '\u{1E4D5}', cursor: 2 })
  })
})

describe.each([
  ['Devanagari', DEVANAGARI],
  ['Mundari Bani', NAG_MUNDARI],
])('%s layout', (_, keyboard) => {
  it('fills every column of every row, so the keys line up', () => {
    for (const row of keyboard.rows) expect(row).toHaveLength(keyboard.columns)
  })

  it('has each key once', () => {
    const keys = keyboard.rows.flat()
    expect(new Set(keys).size).toBe(keys.length)
  })
})
