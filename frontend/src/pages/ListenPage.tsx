import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { ApiError } from "../api/client";
import * as api from "../api/endpoints";
import type { Clip, Script } from "../api/types";
import { Choice } from "../components/Choice";
import { ErrorMessage } from "../components/ErrorMessage";
import { KeyboardTextarea } from "../keyboard/KeyboardTextarea";
import { ScriptWarning } from "../text/ScriptWarning";

const EMPTY = { transcription: "", hi: "", en: "" };
// Mundari Bani first: most listeners write in it. Devanagari stays available.
const SCRIPTS = ["Nagm", "Deva"] as const satisfies Script[];
type WriteScript = (typeof SCRIPTS)[number];

/**
 * Listen and write (ADR-035): play someone else's recording and write what is said in
 * Mundari Bani or Devanagari, with optional Hindi and English translations. Saving or skipping brings the next.
 */
export function ListenPage() {
  const { t } = useTranslation();
  const [clip, setClip] = useState<Clip | null>(null);
  const [none, setNone] = useState(false);
  const [skipped, setSkipped] = useState<string[]>([]);
  const [text, setText] = useState(EMPTY);
  const [script, setScript] = useState<WriteScript>("Nagm");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(0);
  const [error, setError] = useState<unknown>(null);

  const fetchClip = useCallback(
    (exclude: string[]) =>
      api.nextClip(exclude).then(
        (next) => {
          setClip(next);
          setNone(false);
        },
        (failure: unknown) => {
          setClip(null);
          if (
            failure instanceof ApiError &&
            failure.code === "no_clip_available"
          )
            setNone(true);
          else setError(failure);
        },
      ),
    [],
  );

  const load = (exclude: string[]) => {
    setError(null);
    setText(EMPTY);
    return fetchClip(exclude);
  };

  useEffect(() => {
    void fetchClip([]);
  }, [fetchClip]);

  const skip = () => {
    if (!clip) return;
    const next = [...skipped, clip.recording_id];
    setSkipped(next);
    void load(next);
  };

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!clip) return;
    setBusy(true);
    setError(null);
    try {
      await api.writeClip(clip.recording_id, {
        transcription: text.transcription,
        script,
        ...(text.hi.trim() ? { translation_hi: text.hi } : {}),
        ...(text.en.trim() ? { translation_en: text.en } : {}),
      });
      setSaved((count) => count + 1);
      await load(skipped);
    } catch (failure) {
      // Someone else wrote this one down first: move on to another.
      if (failure instanceof ApiError && failure.code === "already_transcribed")
        await load(skipped);
      else setError(failure);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section>
      <h1>{t("listen.title")}</h1>
      <p className="note">{t("listen.intro")}</p>
      {saved > 0 && (
        <p className="note" role="status">
          {t("listen.saved", { count: saved })}
        </p>
      )}
      <ErrorMessage error={error} />
      {none && <p>{t("listen.none")}</p>}
      {clip && (
        <form className="form" onSubmit={(event) => void save(event)}>
          <audio
            key={clip.recording_id}
            controls
            preload="auto"
            aria-label={t("listen.player")}
          >
            {clip.sources.map((source) => (
              <source
                key={source.url}
                src={source.url}
                type={source.content_type}
              />
            ))}
          </audio>
          <Choice
            name="script"
            legend={t("listen.script")}
            options={SCRIPTS.map((value) => ({
              value,
              label: t(`scripts.${value}`),
            }))}
            value={script}
            onChange={setScript}
          />
          <KeyboardTextarea
            label={t("listen.transcription")}
            rows={4}
            lang={script === "Nagm" ? "unr-Nagm" : "unr"}
            spellCheck={false}
            required
            value={text.transcription}
            onValue={(transcription) => setText({ ...text, transcription })}
            script={script}
          />
          <ScriptWarning text={text.transcription} script={script} />
          <KeyboardTextarea
            label={t("text.translation.hi")}
            rows={2}
            lang="hi"
            value={text.hi}
            onValue={(hi) => setText({ ...text, hi })}
            script="Deva"
          />
          <KeyboardTextarea
            label={t("text.translation.en")}
            rows={2}
            lang="en"
            value={text.en}
            onValue={(en) => setText({ ...text, en })}
            script="Latn"
          />
          <div className="wizard-nav">
            <button
              type="button"
              className="action"
              onClick={skip}
              disabled={busy}
            >
              {t("listen.skip")}
            </button>
            <button
              type="submit"
              className="action primary"
              disabled={busy || !text.transcription.trim()}
            >
              {t("listen.save")}
            </button>
          </div>
        </form>
      )}
      <p>
        <Link to="/">{t("listen.done")}</Link>
      </p>
    </section>
  );
}
