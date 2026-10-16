import type { ReactNode } from 'react'
import type { RouteObject } from 'react-router'

import { RequireAuth } from './auth/session'
import { Layout } from './components/Layout'
import { CataloguePage } from './pages/CataloguePage'
import { ChooseSpeakerPage } from './pages/ChooseSpeakerPage'
import { ConsentPage } from './pages/ConsentPage'
import { ExportsPage } from './pages/ExportsPage'
import { FailedJobsPage } from './pages/FailedJobsPage'
import { HomePage } from './pages/HomePage'
import { LoginPage } from './pages/LoginPage'
import { MySubmissionsPage } from './pages/MySubmissionsPage'
import { SubmissionPage } from './pages/SubmissionPage'
import { NewSubmissionPage } from './pages/NewSubmissionPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { ReleasePage } from './pages/ReleasePage'
import { ReleasesPage } from './pages/ReleasesPage'
import { ReportsPage } from './pages/ReportsPage'
import { WithdrawalsPage } from './pages/WithdrawalsPage'

const signedIn = (page: ReactNode) => <RequireAuth>{page}</RequireAuth>

export const routes: RouteObject[] = [
  {
    path: '/',
    element: <Layout />,
    children: [
      { index: true, element: signedIn(<HomePage />) },
      { path: 'login', element: <LoginPage /> },
      { path: 'contribute', element: signedIn(<ChooseSpeakerPage />) },
      { path: 'contribute/:speakerId/new', element: signedIn(<NewSubmissionPage />) },
      { path: 'drafts/:draftId', element: signedIn(<NewSubmissionPage />) },
      { path: 'speakers/:speakerId/consent', element: signedIn(<ConsentPage />) },
      { path: 'submissions', element: signedIn(<MySubmissionsPage />) },
      { path: 'submissions/:submissionId', element: signedIn(<SubmissionPage />) },
      { path: 'withdrawals', element: signedIn(<WithdrawalsPage />) },
      { path: 'catalogue', element: signedIn(<CataloguePage />) },
      { path: 'datasets', element: signedIn(<ReleasesPage />) },
      { path: 'datasets/:releaseId', element: signedIn(<ReleasePage />) },
      { path: 'exports', element: signedIn(<ExportsPage />) },
      { path: 'admin/jobs', element: signedIn(<FailedJobsPage />) },
      { path: 'admin/reports', element: signedIn(<ReportsPage />) },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]
