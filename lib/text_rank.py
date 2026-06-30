"""Small local text-ranking helpers for recall.

The recall plugin should not spend model tokens on ranking, slugging, or
extracting obvious session signals.  This module keeps those computations local
with a dependency-free TF-IDF style scorer.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Iterable, List, Sequence


WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+-]{2,}")

STOP_WORDS = {
    "about", "after", "again", "agent", "agents", "also", "and", "any", "are",
    "because", "been", "before", "being", "but", "can", "code", "codex",
    "context", "could", "current", "did", "does", "doing", "done", "every",
    "file", "files", "for", "from", "get", "git", "had", "has", "have",
    "here", "how", "into", "just", "like", "make", "more", "most", "need",
    "not", "now", "only", "out", "over", "please", "repo", "run", "same",
    "should", "some", "that", "the", "their", "them", "then", "there",
    "these", "this", "those", "through", "to", "try", "use", "used", "using",
    "was", "were", "what", "when", "where", "which", "while", "with", "work",
    "would", "you", "your",
}

ACTION_TERMS = {
    "add", "audit", "blocker", "build", "change", "check", "continue",
    "deploy", "edit", "error", "fail", "failure", "finish", "fix", "goal",
    "implement", "merge", "next", "open", "pending", "problem", "remove",
    "restart", "review", "save", "ship", "test", "update", "verify",
}


def tokenize(text: str) -> List[str]:
    """Return normalized content tokens."""
    tokens = []
    for raw in WORD_RE.findall(text or ""):
        token = raw.lower().strip("_+-")
        if len(token) < 3 or token in STOP_WORDS:
            continue
        tokens.append(token)
    return tokens


def top_terms(texts: Iterable[str], limit: int = 8) -> List[str]:
    """Return high-signal terms across a small document set."""
    docs = [tokenize(t) for t in texts if t]
    if not docs:
        return []

    doc_count = len(docs)
    document_frequency = Counter()
    for tokens in docs:
        document_frequency.update(set(tokens))

    scores = Counter()
    for tokens in docs:
        counts = Counter(tokens)
        for token, count in counts.items():
            idf = math.log((1 + doc_count) / (1 + document_frequency[token])) + 1
            boost = 1.25 if token in ACTION_TERMS else 1.0
            scores[token] += (1 + math.log(count)) * idf * boost

    return [term for term, _score in scores.most_common(limit)]


def rank_texts(texts: Sequence[str], limit: int = 5, query_terms: Sequence[str] | None = None) -> List[str]:
    """Select the most informative snippets from *texts*.

    This is extractive: it returns original snippets, never generated claims.
    """
    unique = []
    seen = set()
    for text in texts:
        cleaned = " ".join((text or "").split())
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        unique.append(cleaned)

    docs = [tokenize(text) for text in unique]
    if not docs:
        return []

    doc_count = len(docs)
    document_frequency = Counter()
    for tokens in docs:
        document_frequency.update(set(tokens))

    query = set(query_terms or [])
    scored = []
    for index, tokens in enumerate(docs):
        if not tokens:
            continue
        counts = Counter(tokens)
        score = 0.0
        for token, count in counts.items():
            idf = math.log((1 + doc_count) / (1 + document_frequency[token])) + 1
            score += (1 + math.log(count)) * idf
            if token in ACTION_TERMS:
                score += 0.75
            if token in query:
                score += 1.0

        # Prefer compact, information-dense snippets. Long transcript chunks
        # should not crowd out a precise request.
        score = score / math.sqrt(len(tokens))
        scored.append((score, -index, unique[index]))

    ranked = sorted(scored, reverse=True)
    return [text for _score, _neg_index, text in ranked[:limit]]


def score_text(query: str, text: str) -> float:
    """Return a local relevance score for *text* against *query*."""
    query_tokens = tokenize(query)
    text_tokens = tokenize(text)
    if not query_tokens or not text_tokens:
        return 0.0

    query_counts = Counter(query_tokens)
    text_counts = Counter(text_tokens)
    score = 0.0
    covered = 0
    for token, query_count in query_counts.items():
        text_count = text_counts.get(token, 0)
        if not text_count:
            text_count = sum(count for text_token, count in text_counts.items() if token in text_token)
        if text_count:
            covered += 1
            score += (1 + math.log(text_count)) * (1 + math.log(query_count))
            if token in ACTION_TERMS:
                score += 0.5

    coverage = covered / len(query_counts)
    density = score / math.sqrt(len(text_tokens))
    return density + (coverage * 2.0)


def rank_query_texts(query: str, texts: Sequence[str], limit: int = 8) -> List[tuple[int, float]]:
    """Rank text indexes for a query.

    Uses scikit-learn TF-IDF cosine scoring when available, otherwise falls
    back to the lightweight scorer above.  The fallback keeps recall usable in
    plugin installs that do not ship optional ML dependencies.
    """
    if not texts:
        return []

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), lowercase=True)
        matrix = vectorizer.fit_transform([query, *texts])
        scores = cosine_similarity(matrix[0], matrix[1:]).ravel()
        ranked = sorted(enumerate(scores), key=lambda item: item[1], reverse=True)
        return [(index, float(score)) for index, score in ranked[:limit] if score > 0]
    except Exception:
        ranked = sorted(
            ((index, score_text(query, text)) for index, text in enumerate(texts)),
            key=lambda item: item[1],
            reverse=True,
        )
        return [(index, score) for index, score in ranked[:limit] if score > 0]


def slug_from_text(text: str, fallback: str = "session-restart", max_words: int = 4) -> str:
    """Build a short, filesystem-safe slug from text."""
    terms = tokenize(text)
    if not terms:
        terms = tokenize(fallback)
    selected = terms[:max_words] or ["session", "restart"]
    slug = "-".join(selected)
    slug = re.sub(r"[^a-z0-9-]+", "-", slug).strip("-")
    return slug or "session-restart"
