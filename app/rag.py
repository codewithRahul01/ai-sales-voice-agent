"""RAG retrieval: knowledge/*.md is split into sections and ranked with BM25.

BM25 keeps the prototype dependency-free and fully explainable. The `search()` interface is
the only thing the agent uses, so production can swap in embeddings + pgvector/Qdrant
(hybrid BM25 + vector) without touching the agent.
"""
import math
import re
from collections import Counter
from dataclasses import dataclass

from . import config

STOPWORDS = set("a an the is are was were be to of and or in on for with at by from it this that what how do "
                "does can i you we my your our me us much many".split())


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS]


@dataclass
class Chunk:
    source: str
    title: str
    text: str


class KnowledgeBase:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.chunks: list[Chunk] = []
        self.load()

    def load(self):
        self.chunks = []
        for path in sorted(config.KNOWLEDGE_DIR.glob("*.md")):
            for section in re.split(r"\n(?=# )", path.read_text(encoding="utf-8")):
                lines = section.strip().splitlines()
                if not lines:
                    continue
                title = lines[0].lstrip("# ").strip()
                self.chunks.append(Chunk(path.name, title, section.strip()))
        self.docs = [tokenize(c.text) + tokenize(c.title) * 2 for c in self.chunks]  # title boost
        self.avgdl = sum(map(len, self.docs)) / max(len(self.docs), 1)
        df = Counter(t for d in self.docs for t in set(d))
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.tfs = [Counter(d) for d in self.docs]

    def search(self, query: str, k: int = 3) -> list[Chunk]:
        q = tokenize(query)
        scored = []
        for i, tf in enumerate(self.tfs):
            dl = len(self.docs[i])
            s = sum(self.idf.get(t, 0) * tf[t] * (self.k1 + 1) /
                    (tf[t] + self.k1 * (1 - self.b + self.b * dl / self.avgdl)) for t in q if t in tf)
            if s > 0:
                scored.append((s, i))
        scored.sort(reverse=True)
        return [self.chunks[i] for _, i in scored[:k]]


kb = KnowledgeBase()
