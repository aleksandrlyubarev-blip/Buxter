from pathlib import Path

import pytest

from buxter.config import Settings


@pytest.fixture
def tmp_out_dir(tmp_path: Path) -> Path:
    out = tmp_path / "out"
    out.mkdir()
    return out


@pytest.fixture
def settings(tmp_out_dir: Path) -> Settings:
    return Settings(
        ANTHROPIC_API_KEY="sk-test",
        BUXTER_OUTPUT_DIR=tmp_out_dir,
        BUXTER_MODEL="opus",
        BUXTER_RUN_TIMEOUT=60,
    )
