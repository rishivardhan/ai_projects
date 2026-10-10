"""Step 4 - Retrieval (the "R" in RAG).

Two kinds of unstructured text are worth retrieving for a CRM assistant:

* **Knowledge base** - product catalog, pricing/discount policy, playbook,
  objection handling, SLAs (markdown files in ``rag/knowledge``), chunked by heading.
* **Interaction notes** - the free-text notes on calls, emails, meetings, demos and
  tickets stored in the ``interactions`` collection, one chunk per interaction,
  carrying ``account_id`` / ``opportunity_id`` metadata so retrieval can be scoped.

Ranking is Okapi BM25 implemented in pure Python - no embedding service or vector DB
is required, the index is rebuilt in milliseconds at startup and updated
incrementally when the agent logs a new interaction. ``Retriever`` is the only
interface the tools depend on, so swapping in a vector store later is a local change.
"""
from __future__ import annotations

import math
import re
import threading
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from ..config import KNOWLEDGE_DIR

_STOPWORDS = set("""
a an and are as at be by for from has have in is it its of on or that the this to was were will
with we they their our you your i he she them his her not but if than then so do does did can
about into over under per up out what which who whom how when where why all any each also
""".split())
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _stem(tok: str) -> str:
    # Tiny suffix stripper: good enough to match "discounts"/"discount", "renewals"/"renewal".
    for suffix in ("ing", "ies", "es", "s", "ed"):
        if len(tok) > len(suffix) + 2 and tok.endswith(suffix):
            return tok[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return tok


def tokenize(text: str) -> list[str]:
    return [_stem(t) for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


@dataclass
class Chunk:
    id: str
    source: str  # "knowledge_base" | "interactions"
    title: str
    text: str
    metadata: dict = field(default_factory=dict)


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.chunks: list[Chunk] = []
        self._tfs: list[Counter] = []
        self._lens: list[int] = []
        self._df: Counter = Counter()

    def add(self, chunk: Chunk) -> None:
        toks = tokenize(f"{chunk.title} {chunk.text}")
        tf = Counter(toks)
        self.chunks.append(chunk)
        self._tfs.append(tf)
        self._lens.append(len(toks))
        self._df.update(tf.keys())

    def __len__(self) -> int:
        return len(self.chunks)

    def search(self, query: str, top_k: int = 5, where=None) -> list[tuple[Chunk, float]]:
        q = tokenize(query)
        if not q or not self.chunks:
            return []
        n = len(self.chunks)
        avgdl = sum(self._lens) / n
        scored = []
        for i, (chunk, tf) in enumerate(zip(self.chunks, self._tfs, strict=True)):
            if where and not where(chunk):
                continue
            score = 0.0
            for term in q:
                f = tf.get(term)
                if not f:
                    continue
                idf = math.log(1 + (n - self._df[term] + 0.5) / (self._df[term] + 0.5))
                score += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self._lens[i] / avgdl))
            if score > 0:
                scored.append((chunk, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


def load_knowledge_chunks(directory: Path = KNOWLEDGE_DIR) -> list[Chunk]:
    """Split each markdown file into one chunk per '## ' section."""
    chunks = []
    for path in sorted(directory.glob("*.md")):
        doc_title, section, buf = path.stem, None, []
        lines = path.read_text().splitlines() + ["## __end__"]
        for line in lines:
            if line.startswith("# "):
                doc_title = line[2:].strip()
            elif line.startswith("## "):
                if section and "".join(buf).strip():
                    chunks.append(Chunk(
                        id=f"KB:{path.stem}#{len(chunks)}", source="knowledge_base",
                        title=f"{doc_title} > {section}", text=" ".join(b.strip() for b in buf).strip(),
                        metadata={"document": path.name, "section": section}))
                section, buf = line[3:].strip(), []
            else:
                buf.append(line)
    return chunks


def interaction_chunk(doc: dict) -> Chunk:
    ts = doc.get("timestamp")
    return Chunk(
        id=doc["_id"], source="interactions",
        title=f"{doc.get('type')} on {ts:%Y-%m-%d}" if ts else str(doc.get("type")),
        text=doc.get("notes", ""),
        metadata={k: doc.get(k) for k in ("account_id", "contact_id", "opportunity_id", "lead_id",
                                          "type", "sentiment", "owner")}
        | {"timestamp": ts.isoformat() if ts else None},
    )


class Retriever:
    """BM25 retriever over the knowledge base and CRM interaction notes."""

    def __init__(self, db):
        self.db = db
        self._lock = threading.Lock()
        self.rebuild()

    def rebuild(self) -> None:
        index = BM25Index()
        for chunk in load_knowledge_chunks():
            index.add(chunk)
        for doc in self.db.interactions.find({}):
            index.add(interaction_chunk(doc))
        with self._lock:
            self.index = index

    def add_interaction(self, doc: dict) -> None:
        with self._lock:
            self.index.add(interaction_chunk(doc))

    def search(self, query: str, *, source: str = "all", account_id: str | None = None,
               opportunity_id: str | None = None, top_k: int = 5) -> list[dict]:
        def where(c: Chunk) -> bool:
            if source != "all" and c.source != source:
                return False
            if account_id and c.source == "interactions" and c.metadata.get("account_id") != account_id:
                return False
            if opportunity_id and c.source == "interactions" and c.metadata.get("opportunity_id") != opportunity_id:
                return False
            return True

        with self._lock:
            hits = self.index.search(query, top_k=top_k, where=where)
        return [{"id": c.id, "source": c.source, "title": c.title, "score": round(s, 3),
                 "text": c.text, "metadata": c.metadata} for c, s in hits]
