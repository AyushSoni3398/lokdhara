"""Test prompts for development only, so the prompted and read modes can be tried.

They are written by the team in Hindi, are not reviewed (Q-X5, Q-G7), and the read sentences
are Hindi placeholders, not Mundari: the real sentence bank waits for Q-X6. The pictures are
flat shapes drawn by `dev_images`. The Latin and Nag Mundari sentences spell the same Hindi
placeholder sound by sound ("yah ek pariksan bakya hai"); a Nag Mundari reader has not checked
them. Their keys start with `test-` so they are easy to retire.
"""

from dataclasses import dataclass, field

SOURCE = "Lokdhara test prompt for development; not reviewed, not for real collection"


@dataclass(frozen=True)
class DevPrompt:
    prompt_key: str
    prompt_type: str
    text: str
    topic_tags: list[str] = field(default_factory=list)
    script_code: str | None = None
    image: str | None = None  # a scene in dev_images.SCENES


DESCRIBE = "इस चित्र में क्या दिख रहा है? इसके बारे में बताइए।"

DEV_PROMPTS = (
    DevPrompt("test-image-house", "image", DESCRIBE, ["home"], image="house"),
    DevPrompt("test-image-river", "image", DESCRIBE, ["nature"], image="river"),
    DevPrompt("test-image-cooking", "image", DESCRIBE, ["food"], image="cooking"),
    DevPrompt("test-situation-rain", "situation", "बारिश के किसी दिन के बारे में बताइए।", ["weather"]),
    DevPrompt(
        "test-situation-market",
        "situation",
        "बाज़ार जाने के बारे में बताइए: आप क्या खरीदते हैं?",
        ["food"],
    ),
    DevPrompt(
        "test-situation-festival",
        "situation",
        "आपको कौन-सा त्योहार पसंद है, और उसमें क्या होता है?",
        ["festival"],
    ),
    DevPrompt(
        "test-read-placeholder",
        "read_sentence",
        "यह एक परीक्षण वाक्य है।",
        ["test"],
        script_code="Deva",
    ),
    DevPrompt(
        "test-read-placeholder-2",
        "read_sentence",
        "यह दूसरा परीक्षण वाक्य है।",
        ["test"],
        script_code="Deva",
    ),
    DevPrompt(
        "test-read-placeholder-latin",
        "read_sentence",
        "Yah ek pariksha vakya hai.",
        ["test"],
        script_code="Latn",
    ),
    DevPrompt(
        "test-read-placeholder-latin-2",
        "read_sentence",
        "Yah doosra pariksha vakya hai.",
        ["test"],
        script_code="Latn",
    ),
    # "yah ek pariksan bakya hai" and "yah dusra pariksan bakya hai", letter by letter.
    DevPrompt(
        "test-read-placeholder-nagm",
        "read_sentence",
        "𞓓𞓕𞓙 𞓤𞓢 𞓑𞓕𞓣𞓚𞓢𞓛𞓕𞓨 𞓗𞓕𞓢𞓓𞓕 𞓙𞓕𞓚",
        ["test"],
        script_code="Nagm",
    ),
    DevPrompt(
        "test-read-placeholder-nagm-2",
        "read_sentence",
        "𞓓𞓕𞓙 𞓡𞓟𞓛𞓣𞓕 𞓑𞓕𞓣𞓚𞓢𞓛𞓕𞓨 𞓗𞓕𞓢𞓓𞓕 𞓙𞓕𞓚",
        ["test"],
        script_code="Nagm",
    ),
)
