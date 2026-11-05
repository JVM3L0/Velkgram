import importlib

import pytest

PACKAGES = [
    "velkgram",
    "velkgram.shared",
    "velkgram.shared.adapters",
    *(
        f"velkgram.{module}.{layer}"
        for module in ("channels", "wishlist", "ingestion", "alerting")
        for layer in ("domain", "ports", "services", "adapters", "web")
    ),
    "velkgram.reporting",
    "velkgram.reporting.ports",
    "velkgram.reporting.services",
    "velkgram.reporting.adapters",
    "velkgram.apps",
    "velkgram.apps.collector",
    "velkgram.apps.web",
    "velkgram.apps.cli",
]


@pytest.mark.parametrize("name", PACKAGES)
def test_package_imports(name: str) -> None:
    importlib.import_module(name)


def test_root_package_name() -> None:
    import velkgram

    assert velkgram.__name__ == "velkgram"
