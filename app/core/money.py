from decimal import Decimal

from app.core.errors import BalanceLimitExceeded

# NUMERIC(18,2) holds at most 16 integer digits. Checking explicitly turns what
# would be a database "numeric field overflow" (a 500) into a clean 409.
MAX_BALANCE = Decimal("9999999999999999.99")


def ensure_within_limit(new_balance: Decimal) -> None:
    if new_balance > MAX_BALANCE:
        raise BalanceLimitExceeded(details={"max_balance": f"{MAX_BALANCE:.2f}"})
