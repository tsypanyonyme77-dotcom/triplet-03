"""Downloads the embedding model into FASTEMBED_CACHE_PATH at image build time, so the first start needs no network."""

from brain.config import ModelsConfig
from brain.knowledge.embedding import make_embedder

embedder, note = make_embedder(ModelsConfig().embeddings)
embedder.embed(["warm"])
print("embedder ready:", embedder.name, note or "")
