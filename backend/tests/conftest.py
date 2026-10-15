import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("ROBOVERSE_DATABASE_URL", "sqlite:///./.test_roboverse.db")

import pytest  # noqa: E402

from roboverse.library.registry import REGISTRY  # noqa: E402
from roboverse.samples import CircuitBuilder, warehouse_amr  # noqa: E402


@pytest.fixture
def registry():
    return REGISTRY


@pytest.fixture
def amr():
    return warehouse_amr()


@pytest.fixture
def cb():
    return CircuitBuilder()
