from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


# Client-generated UUIDs are the V1 wire format. The canonical runtime remains
# the only logical-turn/idempotency authority; this module only validates and
# transports identity metadata across the authenticated PWA boundary.
_REQUEST_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def validate_request_id(value: str) -> str:
    request_id = str(value or '').strip()
    if not request_id or len(request_id) > 64 or not _REQUEST_ID.fullmatch(request_id):
        raise ValueError('request_id must be a canonical UUID')
    return request_id.lower()


class LogicalTurnBody(BaseModel):
    # Security-sensitive identity belongs to the trusted server bridge. Unknown
    # client fields are rejected instead of silently accepting fake authority.
    # Stage 3 intentionally preserves this qualified Stage 1 body shape; input
    # modality is non-authoritative transport metadata carried separately.
    model_config = ConfigDict(extra='forbid')

    request_id: str = Field(min_length=36, max_length=64)
    transcript: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = Field(default=None, max_length=80)

    @field_validator('request_id')
    @classmethod
    def request_id_is_safe(cls, value: str) -> str:
        return validate_request_id(value)
