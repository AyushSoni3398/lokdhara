"""Simulated contributors for the load test (docs/LOAD_TESTING.md).

Each user signs in as one of the accounts made by `loadtest.prepare`, gives consent for their
own voice once, then repeatedly does what the app does: send a recording (create the draft,
upload, sometimes add a transcription, submit), send a text, look at their submissions, or ask
for a prompt. Everything sent is synthetic: tones and placeholder Hindi sentences.
"""

import itertools
import json
import os
import random
import uuid
from pathlib import Path
from typing import Any

from locust import HttpUser, between, task

from loadtest.audio import samples

ACCOUNTS = json.loads((Path(__file__).parent / "results" / "accounts.json").read_text())
_next_account = itertools.cycle(ACCOUNTS)  # gevent runs users in one thread
AUDIO = samples()
SENTENCES = ("यह एक परीक्षण वाक्य है।", "आज मौसम अच्छा है।", "हम गाँव जा रहे हैं।")
API = "/api/v1"


class Contributor(HttpUser):
    # Much busier than a real contributor, who spends minutes on each recording.
    wait_time = between(
        float(os.environ.get("LOADTEST_WAIT_MIN", "1")),
        float(os.environ.get("LOADTEST_WAIT_MAX", "5")),
    )

    def on_start(self) -> None:
        account = next(_next_account)
        session = self.client.post(f"{API}/auth/login", json=account).json()
        self.client.headers["X-CSRF-Token"] = session["csrf_token"]
        self.speaker_id = self._own_speaker()

    def _own_speaker(self) -> str:
        with self.client.post(
            f"{API}/speakers", json={"for_self": True}, catch_response=True
        ) as response:
            if response.status_code == 409:  # a user signed in again after a restart
                response.success()
                speakers = self.client.get(f"{API}/speakers?mine=true").json()["items"]
                speaker = next(s for s in speakers if s["is_self"])
            else:
                speaker = response.json()
        if not speaker["has_active_consent"]:
            form = self.client.get(f"{API}/consent-forms/current?language=hi").json()
            answers = {"consent_form_id": form["id"], "method": "in_app"}
            answers |= {"allow_store_and_review": True}
            self.client.post(
                f"{API}/speakers/{speaker['id']}/consents",
                files={"consent": (None, json.dumps(answers))},
                name=f"{API}/speakers/[id]/consents",
            )
        return str(speaker["id"])

    def _draft(self, kind: str, **fields: Any) -> str:
        body = {
            "client_submission_id": str(uuid.uuid4()),
            "speaker_id": self.speaker_id,
            "kind": kind,
            "content_type": "sentence_list",
            "collection_method": "self_recorded",
            **fields,
        }
        return str(self.client.post(f"{API}/submissions", json=body).json()["id"])

    def _text(self, submission_id: str, **fields: Any) -> dict[str, Any]:
        body = {"language_tag": "unr", "script_code": "Deva", **fields}
        response = self.client.post(
            f"{API}/submissions/{submission_id}/text-layers",
            json=body,
            name=f"{API}/submissions/[id]/text-layers",
        )
        result: dict[str, Any] = response.json()
        return result

    def _submit(self, submission_id: str) -> None:
        self.client.post(
            f"{API}/submissions/{submission_id}/submit", name=f"{API}/submissions/[id]/submit"
        )

    @task(4)
    def send_recording(self) -> None:
        fields: dict[str, Any] = {"recording_mode": "free"}
        if random.random() < 0.3:
            prompt = self.client.get(f"{API}/prompts/next?type=situation").json()
            fields = {"recording_mode": "prompted", "prompt_id": prompt["id"]}
        submission_id = self._draft("audio", **fields)
        audio = random.choices([a for a, _ in AUDIO], weights=[w for _, w in AUDIO])[0]
        upload = self.client.post(
            f"{API}/submissions/{submission_id}/recordings",
            files={"file": ("recording.wav", audio, "audio/wav")},
            data={"source": "browser_recorder"},
            headers={"Idempotency-Key": str(uuid.uuid4())},
            name=f"{API}/submissions/[id]/recordings",
        )
        if random.random() < 0.5:
            recording_id = upload.json()["recording_id"]
            self._text(
                submission_id,
                layer_type="transcription",
                recording_id=recording_id,
                content=random.choice(SENTENCES),
            )
        self._submit(submission_id)

    @task(1)
    def send_text(self) -> None:
        submission_id = self._draft("text")
        source = self._text(
            submission_id,
            layer_type="standalone",
            entry_type="sentence",
            content=random.choice(SENTENCES),
        )
        self._text(
            submission_id,
            layer_type="translation",
            source_layer_id=source["id"],
            language_tag="en",
            script_code="Latn",
            content="This is a test sentence.",
        )
        self._submit(submission_id)

    @task(3)
    def look_at_submissions(self) -> None:
        self.client.get(f"{API}/auth/me")
        self.client.get(f"{API}/submissions?mine=true&limit=100")

    @task(1)
    def ask_for_prompt(self) -> None:
        self.client.get(f"{API}/prompts/next?type=situation")
