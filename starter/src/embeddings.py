"""Choose a real embedding provider (API or local) and implement this contract."""
from sentence_transformers import SentenceTransformer
from typing import Protocol

class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
        ...

    def embed_query(self, question: str) -> list[float]:
        """Return a query vector compatible with the stored document vectors."""
        ...


class MyEmbedder:
    """TODO: implement a provider adapter; do not silently fall back to mock vectors."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        # raise NotImplementedError("TODO: initialize real embedder and dimensions")
        # Load pretrained model
        self.model = SentenceTransformer(model_name)

        # Get actual embedding dimension
        self.dimensions = self.model.get_embedding_dimension()

        print(f"Model: {self.model_name}")
        print(f"Dimensions: {self.dimensions}")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        # raise NotImplementedError("TODO: embed_documents")
        if not texts:
            return []

        if any(not text.strip() for text in texts):
            raise ValueError("Texts must not contain empty strings")

        vectors = self.model.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True
        )

        return vectors.tolist()

    def embed_query(self, question: str) -> list[float]:
        # raise NotImplementedError("TODO: embed_query")
        vector = self.model.encode(
            question,
            normalize_embeddings=True,
            convert_to_numpy=True
        )

        return vector.tolist()