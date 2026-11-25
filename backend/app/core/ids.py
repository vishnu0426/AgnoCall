"""Identifier validation.

Most primary keys here are PostgreSQL UUID columns. PostgreSQL raises a data error for a value
that is not a UUID ("nope", "123") instead of simply matching nothing, which would surface as a
500 for a mistyped URL or filter. Endpoints validate first and answer 400/404 cleanly.
"""
from uuid import UUID


def is_uuid(value) -> bool:
    try:
        UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False
