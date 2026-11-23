import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import i18n from "../i18n";

import { fakeServer, problem, SESSION } from "../test/fakeServer";
import { renderApp } from "../test/render";

beforeEach(async () => {
  await i18n.changeLanguage("en");
});

const clip = (id: string) => ({
  recording_id: id,
  duration_ms: 2000,
  recording_mode: "free",
  sources: [{ url: `/media/${id}.webm`, content_type: "audio/webm" }],
});

describe("listen and write", () => {
  it("saves what was heard with an optional translation and brings the next clip", async () => {
    let served = 0;
    const { requests } = fakeServer({
      "GET /auth/me": () => ({ body: SESSION }),
      "GET /clips/next.*": () =>
        served++ === 0
          ? { body: clip("r1") }
          : problem(404, "no_clip_available"),
      "POST /clips/r1/text": () => ({
        status: 201,
        body: { transcription_layer_id: "l1" },
      }),
    });
    renderApp("/listen");
    expect(
      await screen.findByLabelText("Recording to write down"),
    ).toBeInTheDocument();
    const save = screen.getByRole("button", { name: "Save and next" });
    expect(save).toBeDisabled(); // what you hear is required
    // Mundari Bani is offered first; this listener writes in Devanagari.
    expect(screen.getByRole("radio", { name: /Mundari Bani/ })).toBeChecked();
    await userEvent.click(screen.getByRole("radio", { name: "Devanagari" }));
    await userEvent.type(
      screen.getByLabelText("What you hear"),
      "एनेम",
    );
    await userEvent.type(
      screen.getByLabelText("English translation (optional)"),
      "Name",
    );
    await userEvent.click(save);

    expect(await screen.findByText(/Saved 1 recording/)).toBeInTheDocument();
    expect(screen.getByText(/nothing to write down/)).toBeInTheDocument();
    expect(requests.find((r) => r.method === "POST")?.body).toEqual({
      transcription: "एनेम",
      script: "Deva",
      translation_en: "Name",
    });
  });

  it("skips a clip and does not ask for it again", async () => {
    const { requests } = fakeServer({
      "GET /auth/me": () => ({ body: SESSION }),
      "GET /clips/next\\?exclude=r1": () => ({ body: clip("r2") }),
      "GET /clips/next": () => ({ body: clip("r1") }),
    });
    renderApp("/listen");
    await screen.findByLabelText("Recording to write down");
    await userEvent.click(
      screen.getByRole("button", { name: "Skip this one" }),
    );
    await waitFor(() =>
      expect(requests.some((r) => r.path === "/clips/next?exclude=r1")).toBe(
        true,
      ),
    );
  });
});
