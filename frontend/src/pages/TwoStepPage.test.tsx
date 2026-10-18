import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'

import i18n from '../i18n'
import { fakeServer, problem, SESSION } from '../test/fakeServer'
import { renderApp } from '../test/render'

const NEEDS_SETUP = { ...SESSION, roles: [], mfa_setup_required: true }
const ADMIN = { ...SESSION, roles: [{ role: 'admin', scope: null }], mfa_enabled: true }
const CODES = ['ABCDE-FGHJK', 'MNPQR-STUVW']

beforeEach(async () => {
  await i18n.changeLanguage('en')
})

describe('two-step sign-in', () => {
  it('asks for the code after a right password', async () => {
    const { requests } = fakeServer({
      'GET /auth/me': () => problem(401, 'not_authenticated'),
      'POST /auth/login': (request) =>
        (request.body as { code?: string } | null)?.code
          ? { body: ADMIN }
          : problem(401, 'mfa_required'),
    })
    renderApp('/')
    await userEvent.type(await screen.findByLabelText('Username'), 'asha')
    await userEvent.type(screen.getByLabelText('Password'), 'a long passphrase')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    const code = await screen.findByLabelText('Code from your authenticator app')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    await userEvent.type(code, '123456')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Service status')).toBeInTheDocument()
    const logins = requests.filter((r) => r.path === '/auth/login').map((r) => r.body)
    expect(logins.map((body) => (body as { code: string | null }).code)).toEqual([null, '123456'])
  })

  it('walks an admin through setup and shows the recovery codes once', async () => {
    let enabled = false
    fakeServer({
      'GET /auth/me': () => ({ body: enabled ? ADMIN : NEEDS_SETUP }),
      'POST /auth/mfa/setup': () => ({
        body: { secret: 'JBSWY3DPEHPK3PXP', uri: 'otpauth://totp/x', qr_svg: '<svg></svg>' },
      }),
      'POST /auth/mfa/confirm': (request) => {
        if ((request.body as { code: string }).code !== '654321')
          return problem(422, 'invalid_mfa_code')
        enabled = true
        return { body: { recovery_codes: CODES } }
      },
    })
    renderApp('/')
    expect(await screen.findByText(/Admins must use two-step sign-in/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('link', { name: 'Set up two-step sign-in' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Start' }))

    expect(await screen.findByAltText(/QR code/)).toBeInTheDocument()
    expect(screen.getByText('JBSWY3DPEHPK3PXP')).toBeInTheDocument()
    const input = screen.getByLabelText(/Enter the 6-digit code/)
    await userEvent.type(input, '111111')
    await userEvent.click(screen.getByRole('button', { name: 'Turn on' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('That code is not right.')

    await userEvent.clear(input)
    await userEvent.type(input, '654321')
    await userEvent.click(screen.getByRole('button', { name: 'Turn on' }))
    expect(await screen.findByText('ABCDE-FGHJK')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'I have written them down' }))
    expect(await screen.findByText('Service status')).toBeInTheDocument()
    expect(screen.queryByText(/Admins must use two-step sign-in/)).not.toBeInTheDocument()
  })
})
