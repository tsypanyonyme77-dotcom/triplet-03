"""The playbook is embedded on every scenario start; a remembered vector must not be made twice, or the first click on the screen waits."""

import pytest

from brain.knowledge import embedding

pytest.importorskip("fastembed")


class _Model:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return [[float(len(t))] + [0.0] * 383 for t in texts]


def _embedder(tmp_path, monkeypatch):
    monkeypatch.setenv("FASTEMBED_CACHE_PATH", str(tmp_path / "fastembed"))
    made = embedding.FastEmbedEmbedder.__new__(embedding.FastEmbedEmbedder)
    made.name, made._model, made._seen = "fastembed:test", _Model(), {}
    made._file = tmp_path / "vectors" / "test.json"
    return made


def test_a_text_embedded_before_is_not_embedded_again(tmp_path, monkeypatch):
    made = _embedder(tmp_path, monkeypatch)

    first = made.embed(["flood", "fire"])
    second = made.embed(["fire", "flood", "smog"])

    assert made._model.calls == [["flood", "fire"], ["smog"]]
    assert second[:2] == [first[1], first[0]]


def test_the_vectors_are_written_to_a_file_beside_the_model(tmp_path, monkeypatch):
    made = _embedder(tmp_path, monkeypatch)
    made.embed(["flood"])

    import json

    assert len(json.loads(made._file.read_text())) == 1
