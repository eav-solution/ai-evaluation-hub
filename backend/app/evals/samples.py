from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

NORMALIZER_REVISION = "1"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SampleSource(StrictModel):
    row_index: int | None = Field(default=None, ge=0)
    event_id: str | None = None
    external_id: str | None = None


class SampleMetadata(StrictModel):
    source: SampleSource | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    normalizer_revision: str = NORMALIZER_REVISION


class ToolCall(StrictModel):
    name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    output: Any = None
    error: str | None = None


class AgentTraceEvent(StrictModel):
    type: str = Field(min_length=1)
    name: str | None = None
    input: Any = None
    output: Any = None
    details: dict[str, Any] = Field(default_factory=dict)
    children: list["AgentTraceEvent"] = Field(default_factory=list)


class ConversationTurn(StrictModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class MCPEvent(StrictModel):
    type: str = Field(min_length=1)
    name: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class MCPServerInfo(StrictModel):
    server_name: str = Field(min_length=1)
    transport: str | None = None


class MCPMetadata(StrictModel):
    servers: list[MCPServerInfo] = Field(default_factory=list)


class TextBlock(StrictModel):
    type: Literal["text"] = "text"
    text: str


class ImageBlock(StrictModel):
    type: Literal["image"] = "image"
    asset_id: str | None = Field(default=None, min_length=1)
    url: str | None = Field(default=None, min_length=1)
    mime_type: str | None = None
    data_base64: str | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def exactly_one_source(self):
        if bool(self.asset_id) == bool(self.url):
            raise ValueError("Image blocks need exactly one of asset_id or url")
        return self


ContentBlock = Annotated[TextBlock | ImageBlock, Field(discriminator="type")]


class SingleTurnSample(SampleMetadata):
    kind: Literal["single_turn"] = "single_turn"
    input: str
    actual_output: str
    expected_output: str | None = None
    context: list[str] | None = None
    retrieval_contexts: list[str] | None = None

    @property
    def contexts(self) -> list[str] | None:
        return self.retrieval_contexts


class AgentTraceSample(SampleMetadata):
    kind: Literal["agent_trace"] = "agent_trace"
    input: str
    actual_output: str
    agent_trace: list[AgentTraceEvent] = Field(min_length=1)
    tools_called: list[ToolCall] = Field(default_factory=list)
    expected_tools: list[ToolCall] = Field(default_factory=list)

    @field_validator("expected_tools", mode="before")
    @classmethod
    def tool_name_shorthand(cls, value):
        return [
            {"name": item} if isinstance(item, str) else item
            for item in (value or [])
        ]


class ConversationSample(SampleMetadata):
    kind: Literal["conversation"] = "conversation"
    turns: list[ConversationTurn] = Field(min_length=1)
    chatbot_role: str | None = None
    conversation_context: list[str] = Field(default_factory=list)
    mcp_metadata: MCPMetadata = Field(default_factory=MCPMetadata)
    mcp_events: list[MCPEvent] = Field(default_factory=list)


def conversation_input_preview(sample: "ConversationSample") -> str:
    return next(
        (turn.content for turn in sample.turns if turn.role == "user"), ""
    )


def conversation_actual_preview(sample: "ConversationSample") -> str:
    return next(
        (
            turn.content
            for turn in reversed(sample.turns)
            if turn.role == "assistant"
        ),
        "",
    )


class MultimodalSample(SampleMetadata):
    kind: Literal["multimodal"] = "multimodal"
    input: list[ContentBlock] = Field(min_length=1)
    actual_output: list[ContentBlock] = Field(min_length=1)
    expected_output: list[ContentBlock] | None = None


def multimodal_input_preview(sample: "MultimodalSample") -> str:
    return " ".join(
        block.text for block in sample.input if block.type == "text"
    ).strip()


def multimodal_actual_preview(sample: "MultimodalSample") -> str:
    return " ".join(
        block.text for block in sample.actual_output if block.type == "text"
    ).strip()


EvaluationSample = Annotated[
    SingleTurnSample | AgentTraceSample | ConversationSample | MultimodalSample,
    Field(discriminator="kind"),
]
