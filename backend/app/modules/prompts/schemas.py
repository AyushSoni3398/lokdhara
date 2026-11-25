import uuid
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.languages import LanguageTag, Script
from app.text_input import MultiLine, SingleLine

PromptType = Literal["image", "situation", "read_sentence"]
PromptStatus = Literal["draft", "approved", "retired"]
# Controlled list to come from Q-X5; until then any short lowercase tag.
TopicTag = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{1,39}$")]
PromptText = Annotated[MultiLine, Field(max_length=1000)]
# What a prompt means in Hindi or English, shown under it (ADR-036).
Translation = Annotated[MultiLine, Field(max_length=1000)]


class PromptCreateRequest(BaseModel):
    """Sent as the JSON field `prompt`; image prompts add an `image` file, any prompt may add
    a spoken version as `audio` for speakers who do not read."""

    prompt_key: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    prompt_type: PromptType
    text: PromptText | None = None
    text_language_tag: LanguageTag | None = None
    script_code: Script | None = None
    translation_hi: Translation | None = None
    translation_en: Translation | None = None
    source_and_licence: SingleLine = Field(max_length=300)
    topic_tags: list[TopicTag] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def _type_rules(self) -> Self:
        if self.prompt_type == "situation" and self.text is None:
            raise ValueError("situation prompts need text")
        if self.prompt_type == "read_sentence" and (self.text is None or self.script_code is None):
            raise ValueError("read_sentence prompts need text and script_code")
        return self


class PromptVersionRequest(BaseModel):
    """Fields left out are copied from the version being edited."""

    text: PromptText | None = None
    text_language_tag: LanguageTag | None = None
    script_code: Script | None = None
    translation_hi: Translation | None = None
    translation_en: Translation | None = None
    source_and_licence: SingleLine | None = Field(default=None, max_length=300)
    topic_tags: list[TopicTag] | None = Field(default=None, max_length=10)


class PromptOut(BaseModel):
    """The library view for reviewers and admins."""

    id: uuid.UUID
    prompt_key: str
    # The sentence number in recording codes: 12 → S012 (ADR-034).
    prompt_number: int
    version: int
    prompt_type: PromptType
    text: str | None
    text_language_tag: str | None
    script_code: str | None
    translation_hi: str | None
    translation_en: str | None
    has_image: bool
    has_audio: bool
    source_and_licence: str
    topic_tags: list[str]
    status: PromptStatus
    created_at: datetime


class PromptListOut(BaseModel):
    items: list[PromptOut]


class ContributorPromptOut(BaseModel):
    """What a contributor sees while recording. Media URLs are short-lived."""

    id: uuid.UUID
    prompt_type: PromptType
    text: str | None
    text_language_tag: str | None
    script_code: str | None
    translation_hi: str | None
    translation_en: str | None
    image_url: str | None
    audio_url: str | None
