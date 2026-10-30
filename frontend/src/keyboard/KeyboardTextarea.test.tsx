import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { beforeEach, describe, expect, it } from 'vitest'

import i18n from '../i18n'
import { KeyboardTextarea } from './KeyboardTextarea'

function Box() {
  const [value, setValue] = useState('')
  return <KeyboardTextarea label="text" value={value} onValue={setValue} />
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
