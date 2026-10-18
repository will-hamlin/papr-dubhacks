"""Untrusted candidate submissions. Neither clients nor search agents supply verification results."""
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator, model_validator


def listing_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('listing URLs must be public HTTPS URLs without credentials')
    if parsed.port not in (None, 443):
        raise ValueError('listing URLs must use the standard HTTPS port')
    return value


class Claim(BaseModel):
    model_config = ConfigDict(extra='forbid')
    field: str = Field(pattern=r'^[a-z][a-z0-9_]{0,39}$')
    value: StrictInt | Annotated[StrictStr, Field(min_length=1, max_length=500)]
    unit: str | None = Field(default=None, max_length=20)


class Candidate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    candidate_id: str = Field(min_length=1, max_length=100)
    url: str = Field(max_length=2000)
    sku: str | None = Field(default=None, min_length=1, max_length=100)
    claims: list[Claim] = Field(min_length=1, max_length=30)

    _url = field_validator('url')(listing_url)

    @model_validator(mode='after')
    def unique_fields(self):
        if len({c.field for c in self.claims}) != len(self.claims):
            raise ValueError('each candidate claim field must be unique')
        return self


class CandidateSubmission(BaseModel):
    model_config = ConfigDict(extra='forbid')
    submission_id: str = Field(min_length=1, max_length=100)
    requirements_id: str = Field(pattern=r'^[0-9a-f]{64}$')
    candidates: list[Candidate] = Field(min_length=1, max_length=10)

    @model_validator(mode='after')
    def unique_candidates(self):
        if len({c.candidate_id for c in self.candidates}) != len(self.candidates):
            raise ValueError('candidate IDs must be unique within a submission')
        return self
