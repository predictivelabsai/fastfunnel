from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from fastfunnel.config import settings


@dataclass(frozen=True)
class DeliveryResult:
    status: str
    detail: str


class PostmarkInvitations:
    """Invitation delivery adapter.

    A missing token is a valid local-development state: the invitation remains
    persisted and the UI reports delivery as pending instead of pretending an
    email was sent.
    """

    endpoint = "https://api.postmarkapp.com/email"

    def send(self, recipient: str, invite_url: str, company_name: str) -> DeliveryResult:
        if not settings.postmark_token:
            return DeliveryResult("pending", "POSTMARK_SERVER_TOKEN is not configured")

        payload = json.dumps(
            {
                "From": "FastFunnel <invites@fastfunnel.app>",
                "To": recipient,
                "Subject": f"Join {company_name} in FastFunnel",
                "TextBody": (
                    f"You have been invited to collaborate on {company_name}'s marketing. "
                    f"Accept the invitation: {invite_url}"
                ),
                "MessageStream": "outbound",
            }
        ).encode()
        request = urllib.request.Request(
            self.endpoint,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Postmark-Server-Token": settings.postmark_token,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                if response.status == 200:
                    return DeliveryResult("sent", "Postmark accepted the invitation")
                return DeliveryResult("failed", f"Postmark returned HTTP {response.status}")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            return DeliveryResult("failed", str(exc))
