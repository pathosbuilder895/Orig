import os

from validation.benchmark.reproducibility import lock_environment


def test_lock_environment_forces_offline_model_discovery(monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "0")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "0")

    report = lock_environment()

    assert os.environ["HF_HUB_OFFLINE"] == "1"
    assert os.environ["TRANSFORMERS_OFFLINE"] == "1"
    assert report.model_hub_offline is True
