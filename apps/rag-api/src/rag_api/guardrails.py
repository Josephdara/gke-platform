"""Model Armor screening for questions, retrieved passages, and answers.

Each check returns a verdict and never raises: when Model Armor cannot be reached, the verdict says
the text was not checked, the request carries on unscreened, and the reason is logged as
guardrail_unavailable. Only filter names and error types are recorded, never the screened text.
"""

from dataclasses import dataclass, field
import logging
import re
import time

import httpx

TEMPLATE = re.compile(r"projects/[a-z0-9-]+/locations/([a-z0-9-]+)/templates/[A-Za-z0-9_-]+\Z")
METADATA_TOKEN_URL = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"


@dataclass(frozen=True)
class Verdict:
    checked: bool
    flagged: bool = False
    filters: list[str] = field(default_factory=list)


UNCHECKED = Verdict(checked=False)


class NoGuardrail:
    """Model Armor off: nothing is screened."""

    async def screen_prompt(self, text: str) -> Verdict:
        return UNCHECKED

    async def screen_response(self, text: str) -> Verdict:
        return UNCHECKED


class MetadataToken:
    """An access token for the Pod's Workload Identity, from the GKE metadata server, reused until
    a minute before it expires."""

    def __init__(self, client: httpx.AsyncClient, clock=time.monotonic):
        self.client = client
        self.clock = clock
        self.token: str | None = None
        self.expires = 0.0

    async def __call__(self) -> str:
        if self.token is None or self.clock() >= self.expires:
            response = await self.client.get(METADATA_TOKEN_URL, headers={"Metadata-Flavor": "Google"})
            response.raise_for_status()
            body = response.json()
            self.token, self.expires = body["access_token"], self.clock() + int(body["expires_in"]) - 60
        return self.token


def matched_filters(result: dict) -> list[str]:
    """The names of the filters whose result, at any depth, reports a match."""
    def matched(value) -> bool:
        if isinstance(value, dict):
            return value.get("matchState") == "MATCH_FOUND" or any(matched(v) for v in value.values())
        return isinstance(value, list) and any(matched(v) for v in value)
    return sorted(name for name, value in result.get("filterResults", {}).items() if matched(value))


class ModelArmor:
    def __init__(self, client: httpx.AsyncClient, template: str, token, logger: logging.Logger | None = None):
        location = TEMPLATE.fullmatch(template)
        if not location:
            raise ValueError("template must be projects/PROJECT/locations/LOCATION/templates/TEMPLATE")
        self.client = client
        self.url = f"https://modelarmor.{location.group(1)}.rep.googleapis.com/v1/{template}"
        self.token = token
        self.logger = logger or logging.getLogger(__name__)

    async def screen_prompt(self, text: str) -> Verdict:
        return await self._screen("sanitizeUserPrompt", {"userPromptData": {"text": text}})

    async def screen_response(self, text: str) -> Verdict:
        return await self._screen("sanitizeModelResponse", {"modelResponseData": {"text": text}})

    async def _screen(self, method: str, body: dict) -> Verdict:
        try:
            response = await self.client.post(f"{self.url}:{method}", json=body,
                                              headers={"Authorization": f"Bearer {await self.token()}"})
            response.raise_for_status()
            result = response.json()["sanitizationResult"]
        except (httpx.HTTPError, KeyError, ValueError) as error:
            status = error.response.status_code if isinstance(error, httpx.HTTPStatusError) else None
            self.logger.warning("guardrail_unavailable", extra={
                "method": method, "error_type": type(error).__name__, "status": status})
            return UNCHECKED
        return Verdict(checked=True, flagged=result.get("filterMatchState") == "MATCH_FOUND",
                       filters=matched_filters(result))
