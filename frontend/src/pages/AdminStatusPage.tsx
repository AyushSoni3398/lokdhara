import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import * as api from "../api/endpoints";
import type { BackupState, ServiceStatus } from "../api/types";
import { hasRole, useSession } from "../auth/session";
import { ErrorMessage } from "../components/ErrorMessage";

// The server asks for at least this much (app.modules.ops.archive.MIN_REASON_LENGTH).
const MIN_REASON = 10;

const size = (bytes: number) =>
  bytes < 1_000_000
    ? `${Math.max(1, Math.round(bytes / 1000))} KB`
    : `${Math.round(bytes / 1_000_000)} MB`;

/** One zip of everything the app holds, for admins, with a reason (ADR-027). */
function ArchiveDownload() {
  const { t } = useTranslation();
  const [reason, setReason] = useState("");
  const ready = reason.trim().length >= MIN_REASON;

  return (
    <>
      <h2>{t("status.archive.title")}</h2>
      <p className="note">{t("status.archive.intro")}</p>
      <label>
        {t("status.archive.reason")}
        <textarea
          rows={2}
          maxLength={500}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </label>
      {ready ? (
        <a className="action" href={api.archiveUrl(reason.trim())} download>
          {t("status.archive.download")}
        </a>
      ) : (
        <p className="note">{t("status.archive.needsReason")}</p>
      )}
    </>
  );
}

/** Admins see whether backups and checks run, and what waits for them (docs/ROADMAP.md M8). */
export function AdminStatusPage() {
  const { t, i18n } = useTranslation();
  const session = useSession();
  const isAdmin = hasRole(session, "admin");
  const [status, setStatus] = useState<ServiceStatus | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (isAdmin) api.getServiceStatus().then(setStatus, setError);
  }, [isAdmin]);

  if (!isAdmin) return <p className="note">{t("status.adminOnly")}</p>;

  const date = (iso: string) =>
    new Date(iso).toLocaleString(i18n.resolvedLanguage);
  // Codes such as "backup_missing:database"; a colon would be read as a namespace.
  const alertText = (code: string) => {
    const key = `status.alerts.${code.replace(":", "_")}`;
    return i18n.exists(key) ? t(key) : t("status.alerts.unknown", { code });
  };

  const backup = (state: BackupState) => (
    <li key={state.kind} className="list-item">
      <strong>{t(`status.backupKind.${state.kind}`)}</strong>
      <span>
        {state.last_success_at
          ? t("status.lastSuccess", {
              date: date(state.last_success_at),
              size: size(state.last_success_bytes ?? 0),
            })
          : t("status.never")}
      </span>
      {state.last_run_succeeded === false && (
        <span className="warning">
          {t("status.lastRunFailed", { detail: state.last_run_detail ?? "" })}
        </span>
      )}
    </li>
  );

  return (
    <section>
      <h1>{t("status.title")}</h1>
      <p className="note">{t("status.intro")}</p>
      <ErrorMessage error={error} />
      {status && (
        <>
          <p className="note">
            {t("status.checkedAt", { date: date(status.checked_at) })}
          </p>
          {status.alerts.length === 0 ? (
            <p className="status">{t("status.allWell")}</p>
          ) : (
            <div className="warning" role="alert">
              <strong>{t("status.attention")}</strong>
              <ul>
                {status.alerts.map((code) => (
                  <li key={code}>{alertText(code)}</li>
                ))}
              </ul>
            </div>
          )}

          <h2>{t("status.backups")}</h2>
          <ul className="list">{status.backups.map(backup)}</ul>

          <h2>{t("status.lastDay")}</h2>
          <ul className="list">
            <li className="list-item">
              <span>
                {t("status.submissions", {
                  sent: status.submissions_last_day,
                  accepted: status.accepted_last_day,
                  rejected: status.rejected_last_day,
                })}
              </span>
              <span>
                {t("status.failedSignIns", {
                  count: status.login_failures_last_day,
                })}
              </span>
            </li>
          </ul>

          <h2>{t("status.waiting")}</h2>
          <ul className="list">
            <li className="list-item">
              <span>{t("status.reports", { count: status.open_reports })}</span>
              <span>
                {t("status.withdrawals", { count: status.open_withdrawals })}
              </span>
              <span>
                {t("status.exports", {
                  count: status.exports_awaiting_approval,
                })}
              </span>
            </li>
          </ul>

          <h2>{t("status.jobs")}</h2>
          <ul className="list">
            <li className="list-item">
              <span>
                {t("status.jobCounts", {
                  queued: status.jobs_queued,
                  running: status.jobs_running,
                  failed: status.jobs_failed_waiting,
                })}
              </span>
              {status.oldest_due_job_since && (
                <span>
                  {t("status.oldestDue", {
                    date: date(status.oldest_due_job_since),
                  })}
                </span>
              )}
            </li>
          </ul>

          <h2>{t("status.server")}</h2>
          <ul className="list">
            <li className="list-item">
              <span>
                {t("status.databaseSize", {
                  size: size(status.database_bytes),
                })}
              </span>
              {status.disk_used_share !== null && (
                <span>
                  {t("status.disk", {
                    share: `${Math.round(status.disk_used_share * 100)}%`,
                  })}
                </span>
              )}
            </li>
          </ul>
        </>
      )}
      <ArchiveDownload />
    </section>
  );
}
