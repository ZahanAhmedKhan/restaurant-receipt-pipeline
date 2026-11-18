"""Tests for src/gemini_client.py: fall back to another model when one is busy."""

import pytest

from src import config, gemini_client


class FakeError(Exception):
    def __init__(self, code):
        super().__init__(f"error {code}")
        self.code = code


class FakeClient:
    """Answers per model: an Exception to raise or a text to return."""

    def __init__(self, answers):
        self.answers = answers
        self.tried = []
        self.models = self

    def generate_content(self, model, contents, config=None):
        self.tried.append(model)
        answer = self.answers[model]
        if isinstance(answer, Exception):
            raise answer
        return type("Response", (), {"text": answer})()


@pytest.fixture
def three_models(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_MODEL", "big")
    monkeypatch.setattr(config, "GEMINI_FALLBACK_MODELS", ["small", "big", "tiny"])


def test_model_list_has_no_duplicates(three_models):
    assert gemini_client.model_list() == ["big", "small", "tiny"]


def test_busy_model_falls_back_to_next(three_models):
    client = FakeClient({"big": FakeError(503), "small": "OK", "tiny": "unused"})
    assert gemini_client.generate("hi", client=client) == "OK"
    assert client.tried == ["big", "small"]


def test_all_busy_raises_clear_error(three_models):
    client = FakeClient({"big": FakeError(503), "small": FakeError(504), "tiny": FakeError(429)})
    with pytest.raises(gemini_client.GeminiUnavailable):
        gemini_client.generate("hi", client=client)


def test_real_errors_are_not_hidden(three_models):
    client = FakeClient({"big": FakeError(400), "small": "OK", "tiny": "OK"})
    with pytest.raises(FakeError):
        gemini_client.generate("hi", client=client)
    assert client.tried == ["big"]
