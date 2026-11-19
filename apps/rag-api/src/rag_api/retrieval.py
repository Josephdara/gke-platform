"""Retrieval interface. Passages come back best first."""

from typing import Protocol

from .prompt import Passage


class Retriever(Protocol):
    async def retrieve(self, question: str) -> list[Passage]: ...

    async def health(self) -> bool: ...


class NoRetriever:
    """Used until a document store is configured: every question gets no passages."""

    async def retrieve(self, question: str) -> list[Passage]:
        return []

    async def health(self) -> bool:
        return True
