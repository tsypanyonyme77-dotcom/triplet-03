"""Text embeddings for the knowledge base. Both embedders run locally, with no network at query time.

`fastembed` is the default: a small ONNX sentence model, downloaded once and then kept in
`model_cache_dir()`, so later starts need no network.
`hashing` needs no model at all: it is a bag-of-words projection, weaker on paraphrase
but always available, and what the tests use.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Protocol

DIMENSIONS = 384
_TOKEN = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class Embedder(Protocol):
    name: str
    dimensions: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _normalise(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


class HashingEmbedder:
    name = "hashing-384"
    dimensions = DIMENSIONS

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vector = [0.0] * self.dimensions
            words = tokens(text)
            for term in words + [f"{a}_{b}" for a, b in zip(words, words[1:])]:
                digest = hashlib.blake2b(term.encode(), digest_size=8).digest()
                index = int.from_bytes(digest[:4], "big") % self.dimensions
                vector[index] += 1.0 if digest[4] & 1 else -1.0
            vectors.append(_normalise(vector))
        return vectors


def model_cache_dir() -> Path:
    """Where the embedding model is kept. fastembed's own default is the system temp directory,
    which a reboot empties; `FASTEMBED_CACHE_PATH` overrides this."""
    override = os.environ.get("FASTEMBED_CACHE_PATH")
    if override:
        return Path(override)
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "city-brain" / "fastembed"


class FastEmbedEmbedder:
    """Remembers every vector it has made, in memory and in a file beside the model: the playbook is embedded on every scenario start
    and takes about eight seconds, so without this the first thing the screen does after a click is wait."""

    dimensions = DIMENSIONS

    def __init__(self, model: str = "BAAI/bge-small-en-v1.5") -> None:
        from fastembed import TextEmbedding

        self.name = f"fastembed:{model}"
        # fastembed reads the cache first and contacts the Hugging Face Hub only if the model is missing.
        self._model = TextEmbedding(model_name=model, cache_dir=str(model_cache_dir()))
        self._file = model_cache_dir().parent / "vectors" / (re.sub(r"[^a-z0-9]+", "-", model.lower()) + ".json")
        try:
            self._seen: dict[str, list[float]] = json.loads(self._file.read_text())
        except (OSError, ValueError):
            self._seen = {}

    def embed(self, texts: list[str]) -> list[list[float]]:
        keys = [hashlib.sha1(text.encode()).hexdigest() for text in texts]
        missing = list(dict.fromkeys(k for k in keys if k not in self._seen))
        if missing:
            by_key = dict(zip(keys, texts))
            for key, vector in zip(missing, self._model.embed([by_key[k] for k in missing])):
                self._seen[key] = _normalise([float(v) for v in vector])
            try:
                self._file.parent.mkdir(parents=True, exist_ok=True)
                temp = self._file.with_suffix(f".{os.getpid()}.tmp")
                temp.write_text(json.dumps(self._seen))
                temp.replace(self._file)
            except OSError:  # a cache that cannot be written only costs the wait next time
                pass
        return [self._seen[k] for k in keys]


_LOADED: dict[str, FastEmbedEmbedder] = {}  # the model takes most of a second to load; every scenario shares one


def make_embedder(provider: str = "auto", model: str = "BAAI/bge-small-en-v1.5") -> tuple[Embedder, str]:
    """Returns (embedder, note). `auto` prefers fastembed and falls back to hashing if it cannot load."""
    if provider == "hashing":
        return HashingEmbedder(), ""
    try:
        if model not in _LOADED:
            _LOADED[model] = FastEmbedEmbedder(model)
        return _LOADED[model], ""
    except Exception as error:
        if provider == "fastembed":
            raise
        return HashingEmbedder(), f"fastembed unavailable ({type(error).__name__}: {error}); using the hashing embedder"


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))
