import { screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import i18n from '../i18n'
import { fakeServer, SESSION } from '../test/fakeServer'
import { renderApp } from '../test/render'

const ADMIN = { ...SESSION, roles: [{ role: 'admin', scope: null }] }
const BACKUP = {
  kind: 'database',
  last_run_at: '2026-10-18T21:31:00Z',
  last_run_succeeded: true,
  last_run_detail: null,
  last_success_at: '2026-10-18T21:31:00Z',
  last_success_bytes: 42_000_000,
}
const STATUS = {
  checked_at: '2026-10-19T08:00:00Z',
  alerts: [],
  jobs_queued: 2,
  jobs_running: 1,
  oldest_due_job_since: null,
  jobs_failed_last_day: 0,
  jobs_failed_waiting: 0,
  backups: [
    BACKUP,
    {
      ...BACKUP,
      kind: 'withdrawal_log',
      last_success_bytes: 900,
      last_run_succeeded: false,
      last_run_detail: 'failed during: copying off-site',
    },
  ],
  submissions_last_day: 12,
  accepted_last_day: 10,
  rejected_last_day: 1,
  login_failures_last_day: 3,
  open_reports: 2,
  open_withdrawals: 1,
  exports_awaiting_approval: 0,
  database_bytes: 120_000_000,
  disk_used_share: 0.41,
}

beforeEach(async () => {
  await i18n.changeLanguage('en')
})

describe('service status', () => {
  it('shows an admin that all is well, with the counts', async () => {
    fakeServer({
      'GET /auth/me': () => ({ body: ADMIN }),
      'GET /admin/status': () => ({ body: STATUS }),
    })
    renderApp('/admin/status')

    expect(await screen.findByText('Nothing needs attention.')).toBeInTheDocument()
    expect(screen.getAllByText(/Last success: .* \(42 MB\)/)).toHaveLength(1)
    expect(screen.getAllByText(/Last success: .* \(1 KB\)/)).toHaveLength(1)
    expect(
      screen.getByText('The last run failed: failed during: copying off-site'),
    ).toBeInTheDocument()
    expect(screen.getByText('12 sent, 10 accepted, 1 rejected by the checks')).toBeInTheDocument()
    expect(screen.getByText('Reports: 2')).toBeInTheDocument()
    expect(screen.getByText('2 waiting, 1 running, 0 failed')).toBeInTheDocument()
    expect(screen.getByText('Disk 41% full')).toBeInTheDocument()
  })

  it('puts what needs attention first, in plain words', async () => {
    fakeServer({
      'GET /auth/me': () => ({ body: ADMIN }),
      'GET /admin/status': () => ({
        body: { ...STATUS, alerts: ['backup_missing:database', 'queue_behind', 'new_code'] },
      }),
    })
    renderApp('/admin/status')

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('No successful database backup in the last 26 hours.')
    expect(alert).toHaveTextContent('Is the worker running?')
    expect(alert).toHaveTextContent('Something needs attention (new_code).')
  })

  it('is only for admins', async () => {
    fakeServer({ 'GET /auth/me': () => ({ body: SESSION }) })
    renderApp('/admin/status')
    expect(await screen.findByText('Only admins can see this page.')).toBeInTheDocument()
  })
})
