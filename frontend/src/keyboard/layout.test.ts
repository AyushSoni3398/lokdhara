import { describe, expect, it } from 'vitest'

import { DEVANAGARI, deleteBack, insertAt, keyLabel } from './layout'

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

describe.each([['Devanagari', DEVANAGARI]])('%s layout', (_, keyboard) => {
  it('fills every column of every row, so the keys line up', () => {
    for (const row of keyboard.rows) expect(row).toHaveLength(keyboard.columns)
  })

  it('has each key once', () => {
    const keys = keyboard.rows.flat()
    expect(new Set(keys).size).toBe(keys.length)
  })
})
