"""
Ticket service: builds dependencies and calls SD ticket API.
"""

from app.sd.client import SDClient
from app.sd.users_api import get_user
from app.sd.tickets_api import create_ticket, TicketCreateResult


def create_simple_ticket(settings, token: str, sd_user_id: int, title: str, description: str) -> TicketCreateResult:
    client = SDClient(
        base_url=settings.sd_base_url,
        api_prefix=settings.sd_api_prefix,
        timeout_seconds=settings.http_timeout_seconds,
    )

    profile = get_user(client, user_id=sd_user_id, token=token)
    if not profile.address:
        raise RuntimeError("User address is missing in SD profile")

    return create_ticket(
        client=client,
        token=token,
        title=title,
        description=description,
        author_id=sd_user_id,
        address_id=profile.address.id,
        category=None,
        service=None,
        kind="TICKET_VS",
    )
