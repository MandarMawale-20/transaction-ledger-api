from sqlalchemy.exc import IntegrityError


def constraint_name(exc: IntegrityError) -> str | None:
    """Name of the violated constraint (psycopg exposes it on diag)."""
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None)
