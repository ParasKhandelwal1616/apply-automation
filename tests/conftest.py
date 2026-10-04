from pathlib import Path

import pytest

from apply_bot.config import load_settings


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def settings():
    return load_settings()


@pytest.fixture
def roadvision_text() -> str:
    return (FIXTURES / "roadvision.txt").read_text(encoding="utf-8")


@pytest.fixture
def stance_text() -> str:
    return (FIXTURES / "stance.txt").read_text(encoding="utf-8")
