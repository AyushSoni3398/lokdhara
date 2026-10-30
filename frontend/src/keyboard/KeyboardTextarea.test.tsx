import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { beforeEach, describe, expect, it } from 'vitest'

import type { Script } from '../api/types'
import i18n from '../i18n'
import { KeyboardTextarea } from './KeyboardTextarea'

function Box({ script = 'Deva' }: { script?: Script }) {
  const [value, setValue] = useState('')
  return <KeyboardTextarea label="text" script={script} value={value} onValue={setValue} />
}

describe('KeyboardTextarea', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en')
  })

  it('types letters, matras and numbers from one layout', async () => {
    const user = userEvent.setup()
    render(<Box />)
    await user.click(screen.getByRole('button', { name: 'Hindi keyboard' }))
    await user.click(screen.getByRole('button', { name: 'न' }))
    await user.click(screen.getByRole('button', { name: '◌ा' }))
    await user.click(screen.getByRole('button', { name: 'म' }))
    await user.click(screen.getByRole('button', { name: '१' }))
    expect(screen.getByRole('textbox', { name: 'text' })).toHaveValue('नाम१')
    await user.click(screen.getByRole('button', { name: 'Delete' }))
    await user.click(screen.getByRole('button', { name: 'Delete' }))
    expect(screen.getByRole('textbox', { name: 'text' })).toHaveValue('ना')
  })

  it('starts a new line', async () => {
    const user = userEvent.setup()
    render(<Box />)
    await user.click(screen.getByRole('button', { name: 'Hindi keyboard' }))
    await user.click(screen.getByRole('button', { name: 'न' }))
    await user.click(screen.getByRole('button', { name: 'New line' }))
    await user.click(screen.getByRole('button', { name: 'म' }))
    expect(screen.getByRole('textbox', { name: 'text' })).toHaveValue('न\nम')
  })
})

describe('KeyboardTextarea for other scripts', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en')
  })

  it('types Mundari Bani letters and signs', async () => {
    const user = userEvent.setup()
    render(<Box script="Nagm" />)
    await user.click(screen.getByRole('button', { name: 'Mundari Bani keyboard' }))
    expect(screen.queryByRole('button', { name: 'ABC → हिंदी' })).toBeNull()
    await user.click(screen.getByRole('button', { name: 'a' }))
    await user.click(screen.getByRole('button', { name: 'muhor sign' }))
    await user.click(screen.getByRole('button', { name: '1' }))
    expect(screen.getByRole('textbox', { name: 'text' })).toHaveValue('\u{1E4D5}\u{1E4EC}\u{1E4F1}')
    await user.click(screen.getByRole('button', { name: 'Delete' }))
    expect(screen.getByRole('textbox', { name: 'text' })).toHaveValue('\u{1E4D5}\u{1E4EC}')
  })

  it('offers no keyboard for Roman letters, which every phone has', () => {
    render(<Box script="Latn" />)
    expect(screen.queryByRole('button', { name: /keyboard/ })).toBeNull()
  })
})

describe('KeyboardTextarea Roman typing', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en')
  })

  it('adds Roman letters as Devanagari', async () => {
    const user = userEvent.setup()
    render(<Box />)
    await user.click(screen.getByRole('button', { name: 'Hindi keyboard' }))
    await user.click(screen.getByRole('button', { name: 'ABC → हिंदी' }))
    await user.type(screen.getByRole('textbox', { name: 'Type in Roman letters' }), 'naam')
    await user.click(screen.getByRole('button', { name: 'Add to text' }))
    expect(screen.getByRole('textbox', { name: 'text' })).toHaveValue('नाम ')
  })
})
