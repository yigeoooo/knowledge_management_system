"""LangChain interfaces backed by the application's version-aware data model."""
from collections.abc import Callable
from uuid import UUID

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field

from . import embedding_adapter as provider


class DashScopeEmbeddings(Embeddings):
    def __init__(self, *, documents_fn=None, query_fn=None):
        self.documents_fn = documents_fn or provider.embed_texts
        self.query_fn = query_fn or provider.embed_query
        self.model = None

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors, self.model = self.documents_fn(texts)
        return vectors

    def embed_query(self, text: str) -> list[float]:
        vector, self.model = self.query_fn(text)
        return vector

    def query_with_model(self, text):
        vector = self.embed_query(text)
        return vector, self.model


def source_document(source):
    return Document(page_content=source.get("content") or "",
                    metadata={k: v for k, v in source.items()
                              if k not in {"content", "preview_url", "content_html"}})


def document_source(document):
    return {**document.metadata, "content": document.page_content or None}


class KnowledgeBaseRetriever(BaseRetriever):
    """Hybrid retriever with RRF, optional reranking and section expansion.

    Scope and counts live on this per-invocation instance; it is never shared
    between concurrent requests. Document metadata retains citation identities.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)
    knowledge_base_id: UUID | str
    anchor_id: str | None = None
    material_fn: Callable = Field(exclude=True)
    search_fn: Callable = Field(exclude=True)
    scope: dict = Field(default_factory=dict)
    retrieval_count: int = 0

    def _get_relevant_documents(self, query: str, *, run_manager=None) -> list[Document]:
        material = self.material_fn(self.knowledge_base_id, query,
            anchor_id=self.anchor_id, search_sources_fn=self.search_fn)
        self.scope, self.retrieval_count = material.scope, material.retrieval_count
        return [source_document(s) for s in material.context + material.media]
