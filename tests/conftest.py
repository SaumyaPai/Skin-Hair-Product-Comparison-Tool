import pytest

from app.services import llm_client


@pytest.fixture(autouse=True)
def fresh_cooldowns():
    """Each test starts with no AI 'cooling down' from an earlier test."""
    llm_client.reset_cooldowns()
    yield
    llm_client.reset_cooldowns()
