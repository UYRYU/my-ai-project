"""Text similarity utilities.

Provides cosine and Jaccard similarity for Japanese + English mixed text.
Uses character n-grams (bigrams and trigrams) so it works without a
language-specific tokenizer.
"""
import math


# ---------------------------------------------------------------------------
# Tokenisation
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """Return tokens from *text* using word splits + character n-grams.

    Character n-grams (n=2, 3) give reasonable similarity for Japanese text
    without requiring MeCab or similar morphological analysers.
    """
    tokens: list[str] = list(text.lower().split())
    for n in (2, 3):
        tokens.extend(text[i : i + n] for i in range(len(text) - n + 1))
    return tokens


# ---------------------------------------------------------------------------
# TF-IDF cosine similarity
# ---------------------------------------------------------------------------

def _tf_idf_vector(text: str, corpus: list[str]) -> dict[str, float]:
    tokens = _tokenize(text)
    if not tokens:
        return {}
    total = len(tokens)

    tf: dict[str, float] = {}
    for t in tokens:
        tf[t] = tf.get(t, 0) + 1 / total

    n_docs = len(corpus) + 1
    return {
        term: freq * math.log(n_docs / (sum(1 for doc in corpus if term in doc) + 1))
        for term, freq in tf.items()
    }


def cosine_similarity(text1: str, text2: str) -> float:
    """Return cosine similarity in [0, 1] between *text1* and *text2*."""
    corpus = [text1, text2]
    v1 = _tf_idf_vector(text1, corpus)
    v2 = _tf_idf_vector(text2, corpus)

    all_terms = set(v1) | set(v2)
    dot = sum(v1.get(t, 0.0) * v2.get(t, 0.0) for t in all_terms)
    mag1 = math.sqrt(sum(x * x for x in v1.values()))
    mag2 = math.sqrt(sum(x * x for x in v2.values()))

    if mag1 == 0 or mag2 == 0:
        return 0.0
    return min(dot / (mag1 * mag2), 1.0)


# ---------------------------------------------------------------------------
# Jaccard similarity
# ---------------------------------------------------------------------------

def jaccard_similarity(text1: str, text2: str) -> float:
    """Return Jaccard similarity in [0, 1] between *text1* and *text2*."""
    s1 = set(_tokenize(text1))
    s2 = set(_tokenize(text2))
    if not s1 and not s2:
        return 0.0
    return len(s1 & s2) / len(s1 | s2)


# ---------------------------------------------------------------------------
# Unified interface
# ---------------------------------------------------------------------------

def compute_similarity(text1: str, text2: str, method: str = "cosine") -> float:
    """Compute similarity between two texts using the specified *method*.

    Args:
        text1: First text.
        text2: Second text.
        method: ``"cosine"`` (default) or ``"jaccard"``.

    Returns:
        Similarity score in [0, 1].

    Raises:
        ValueError: If an unknown method is supplied.
    """
    if method == "cosine":
        return cosine_similarity(text1, text2)
    if method == "jaccard":
        return jaccard_similarity(text1, text2)
    raise ValueError(f"Unknown similarity method: {method!r}. Use 'cosine' or 'jaccard'.")
