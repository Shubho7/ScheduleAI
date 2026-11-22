"""Keep real email addresses away from the voice model.

A voice agent can read out anything it has seen, and instructions alone are not a
reliable way to stop that. So in voice mode, email addresses the user types are
replaced with placeholders (GUEST_1, GUEST_2, ...) before the model sees them,
and the calendar tools swap the real address back in when they call Google.
The model never has the address, so it cannot say it.
"""

import re

_EMAIL_IN_TEXT = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_ALIAS = re.compile(r"GUEST_\d+")

# chat_id -> {"GUEST_1": "real@address.com"}
_aliases: dict[str, dict[str, str]] = {}


def hide_emails(chat_id: str, text: str) -> str:
    """Replace every email address in `text` with a stable placeholder."""
    mapping = _aliases.setdefault(chat_id, {})
    by_email = {email.lower(): alias for alias, email in mapping.items()}

    def replace(match: re.Match) -> str:
        email = match.group(0)
        alias = by_email.get(email.lower())
        if alias is None:
            alias = f"GUEST_{len(mapping) + 1}"
            mapping[alias] = email
            by_email[email.lower()] = alias
        return alias

    return _EMAIL_IN_TEXT.sub(replace, text)


def reveal_emails(chat_id: str, text: str) -> str:
    """Swap placeholders in `text` back to the real email addresses."""
    mapping = _aliases.get(chat_id, {})
    return _ALIAS.sub(lambda m: mapping.get(m.group(0), m.group(0)), text)
