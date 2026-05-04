"""pytest 전역 설정."""
from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "network: 네트워크 연결이 필요한 테스트 (CI에서 제외 가능: -m 'not network')",
    )
