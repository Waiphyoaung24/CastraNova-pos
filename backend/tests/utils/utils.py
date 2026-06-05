import random
import string

from fastapi.testclient import TestClient

from app.core.config import settings


def random_lower_string() -> str:
    return "".join(random.choices(string.ascii_lowercase, k=32))


def random_email() -> str:
    return f"{random_lower_string()}@{random_lower_string()}.com"


def assert_no_financial_keys(payload: object) -> None:
    """Recursively assert no cost/margin/budget KEY appears anywhere in a JSON
    response (financial fields must be ABSENT for staff, not blanked). Key-based,
    not a value-substring scan, so a customer/project literally named 'Margin Co'
    cannot false-trip it."""
    forbidden = ("revenue", "cogs", "margin", "budget", "consumed_cost")

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                kl = k.lower()
                assert not any(f in kl for f in forbidden), f"leaked financial key: {k}"
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)


def get_superuser_token_headers(client: TestClient) -> dict[str, str]:
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    tokens = r.json()
    a_token = tokens["access_token"]
    headers = {"Authorization": f"Bearer {a_token}"}
    return headers
