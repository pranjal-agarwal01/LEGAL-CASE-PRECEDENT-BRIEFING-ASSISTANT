from pathlib import Path

import pytest

from legal_brief.config import PROJECT_ROOT, Settings
from legal_brief.corpus import load_corpus


@pytest.fixture(scope="session")
def settings(tmp_path_factory) -> Settings:
    return Settings(output_dir=tmp_path_factory.mktemp("outputs"))


@pytest.fixture(scope="session")
def corpus(settings):
    return load_corpus(str(settings.corpus_path))


@pytest.fixture(scope="session")
def fs_dir() -> Path:
    return PROJECT_ROOT / "data" / "fact_sheets"
