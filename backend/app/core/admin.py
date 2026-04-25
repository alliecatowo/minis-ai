from app.core.config import settings
from app.models.user import User


def is_trusted_admin(user: User | None) -> bool:
    """Return True only for server-trusted admin identities.

    Admin status is intentionally derived from ``ADMIN_USERNAMES`` and the
    authenticated GitHub username claim populated by the server-side auth sync.
    User-editable settings, including the legacy ``user_settings.is_admin``
    column, must never grant admin authorization.
    """
    if user is None or not user.github_username:
        return False

    username = user.github_username.strip().lower()
    return bool(username and username in settings.admin_username_list)
