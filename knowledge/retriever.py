"""
Knowledge Retrieval System
Allows trading agents to query the knowledge base for relevant information
"""
import json
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from loguru import logger

# For text similarity
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    import numpy as np
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False


@dataclass
class RetrievalResult:
    """A knowledge retrieval result"""
    chunk_id: str
    source: str
    title: str
    content: str
    relevance_score: float
    topics: List[str]


class KnowledgeRetriever:
    """
    Retrieves relevant knowledge for trading decisions.

    Usage:
        retriever = KnowledgeRetriever()

        # Query by topic
        results = retriever.query("how to identify support and resistance levels")

        # Query by trading context
        results = retriever.get_context_for_trade(
            symbol="AAPL",
            signal_type="breakout",
            market_type="equity"
        )
    """

    def __init__(self, knowledge_path: str = "knowledge"):
        self.knowledge_path = Path(knowledge_path)
        self.processed_path = self.knowledge_path / "processed"
        self.index_file = self.processed_path / "index.json"

        # Load index
        self.index = self._load_index()

        # Load all chunks into memory for fast retrieval
        self.chunks: Dict[str, Dict] = {}
        self._load_chunks()

        # Build TF-IDF index for similarity search
        self.vectorizer = None
        self.tfidf_matrix = None
        self.chunk_ids = []

        if SKLEARN_AVAILABLE and self.chunks:
            self._build_tfidf_index()

    def _load_index(self) -> Dict:
        """Load knowledge index"""
        if self.index_file.exists():
            with open(self.index_file, 'r') as f:
                return json.load(f)
        return {"files": {}, "chunks": [], "stats": {}}

    def _load_chunks(self) -> None:
        """Load all chunks into memory"""
        if not self.processed_path.exists():
            return

        for chunk_file in self.processed_path.glob("chunk_*.json"):
            try:
                with open(chunk_file, 'r') as f:
                    chunk = json.load(f)
                    self.chunks[chunk["id"]] = chunk
            except (json.JSONDecodeError, KeyError, OSError) as e:
                logger.warning(f"Error loading chunk {chunk_file}: {e}")

        logger.info(f"Loaded {len(self.chunks)} knowledge chunks")

    def _build_tfidf_index(self) -> None:
        """Build TF-IDF index for similarity search"""
        if not self.chunks:
            return

        logger.info("Building TF-IDF index...")

        self.chunk_ids = list(self.chunks.keys())
        documents = [self.chunks[cid]["content"] for cid in self.chunk_ids]

        self.vectorizer = TfidfVectorizer(
            max_features=5000,
            stop_words='english',
            ngram_range=(1, 2)
        )

        self.tfidf_matrix = self.vectorizer.fit_transform(documents)
        logger.info(f"TF-IDF index built with {self.tfidf_matrix.shape[0]} documents")

    def query(self, query_text: str, top_k: int = 5, min_score: float = 0.1) -> List[RetrievalResult]:
        """
        Query the knowledge base with natural language.

        Args:
            query_text: The query string
            top_k: Number of results to return
            min_score: Minimum relevance score threshold

        Returns:
            List of RetrievalResult objects
        """
        if not self.chunks:
            return []

        results = []

        if SKLEARN_AVAILABLE and self.vectorizer and self.tfidf_matrix is not None:
            # Use TF-IDF similarity
            query_vec = self.vectorizer.transform([query_text])
            similarities = cosine_similarity(query_vec, self.tfidf_matrix).flatten()

            # Get top results
            top_indices = np.argsort(similarities)[::-1][:top_k]

            for idx in top_indices:
                score = similarities[idx]
                if score < min_score:
                    continue

                chunk_id = self.chunk_ids[idx]
                chunk = self.chunks[chunk_id]

                results.append(RetrievalResult(
                    chunk_id=chunk_id,
                    source=chunk["source"],
                    title=chunk["title"],
                    content=chunk["content"],
                    relevance_score=float(score),
                    topics=chunk.get("topics", [])
                ))
        else:
            # Fallback: keyword matching
            query_words = set(query_text.lower().split())

            for chunk_id, chunk in self.chunks.items():
                content_words = set(chunk["content"].lower().split())
                overlap = len(query_words & content_words)
                score = overlap / len(query_words) if query_words else 0

                if score >= min_score:
                    results.append(RetrievalResult(
                        chunk_id=chunk_id,
                        source=chunk["source"],
                        title=chunk["title"],
                        content=chunk["content"],
                        relevance_score=score,
                        topics=chunk.get("topics", [])
                    ))

            results.sort(key=lambda x: x.relevance_score, reverse=True)
            results = results[:top_k]

        return results

    def query_by_topic(self, topic: str, top_k: int = 10) -> List[RetrievalResult]:
        """Get chunks related to a specific topic"""
        results = []

        for chunk_id, chunk in self.chunks.items():
            if topic in chunk.get("topics", []):
                results.append(RetrievalResult(
                    chunk_id=chunk_id,
                    source=chunk["source"],
                    title=chunk["title"],
                    content=chunk["content"],
                    relevance_score=1.0,
                    topics=chunk.get("topics", [])
                ))

        return results[:top_k]

    def get_context_for_trade(
        self,
        symbol: str,
        signal_type: str,
        market_type: str,
        additional_context: str = ""
    ) -> List[RetrievalResult]:
        """
        Get relevant knowledge for a specific trade setup.

        Args:
            symbol: Trading symbol (e.g., "AAPL")
            signal_type: Type of signal (e.g., "breakout", "mean_reversion")
            market_type: Market type (e.g., "equity", "crypto", "options")
            additional_context: Any additional context

        Returns:
            Relevant knowledge chunks
        """
        # Build query based on trade context
        query_parts = []

        # Signal type mapping to search terms
        signal_queries = {
            "breakout": "breakout trading strategy resistance levels volume confirmation",
            "mean_reversion": "mean reversion oversold overbought support levels",
            "momentum": "momentum trading trend following relative strength",
            "reversal": "trend reversal pattern confirmation divergence",
            "gap": "gap trading gap fill strategy opening range",
            "volume_surge": "volume analysis accumulation distribution unusual volume",
        }

        if signal_type in signal_queries:
            query_parts.append(signal_queries[signal_type])
        else:
            query_parts.append(signal_type)

        # Market type specific queries
        market_queries = {
            "equity": "stock trading equity market",
            "crypto": "cryptocurrency bitcoin trading",
            "forex": "forex currency trading",
            "options": "options trading calls puts premium"
        }

        if market_type in market_queries:
            query_parts.append(market_queries[market_type])

        if additional_context:
            query_parts.append(additional_context)

        full_query = " ".join(query_parts)

        return self.query(full_query, top_k=3, min_score=0.05)

    def get_risk_management_wisdom(self) -> List[RetrievalResult]:
        """Get knowledge about risk management"""
        return self.query(
            "risk management position sizing stop loss protect capital drawdown",
            top_k=5,
            min_score=0.05
        )

    def get_psychology_insights(self) -> List[RetrievalResult]:
        """Get trading psychology insights"""
        return self.query(
            "trading psychology emotion fear greed discipline patience mental",
            top_k=5,
            min_score=0.05
        )

    def format_context_for_agent(self, results: List[RetrievalResult]) -> str:
        """Format retrieval results as context for agents"""
        if not results:
            return ""

        context_parts = ["Relevant knowledge from trading books:"]

        for i, result in enumerate(results, 1):
            context_parts.append(f"\n[{i}] From '{result.title}':")
            # Truncate long content
            content = result.content[:500] + "..." if len(result.content) > 500 else result.content
            context_parts.append(f"  {content}")

        return "\n".join(context_parts)

    def get_stats(self) -> Dict:
        """Get retriever statistics"""
        topic_counts = {}
        for chunk in self.chunks.values():
            for topic in chunk.get("topics", []):
                topic_counts[topic] = topic_counts.get(topic, 0) + 1

        return {
            "total_chunks": len(self.chunks),
            "indexed": self.tfidf_matrix is not None,
            "topic_distribution": topic_counts
        }


# Singleton instance for agents to use
_retriever_instance: Optional[KnowledgeRetriever] = None


def get_retriever(knowledge_path: str = "trading_knowledge") -> KnowledgeRetriever:
    """Get or create the knowledge retriever instance"""
    global _retriever_instance
    if _retriever_instance is None:
        _retriever_instance = KnowledgeRetriever(knowledge_path=knowledge_path)
    return _retriever_instance


# CLI for testing
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Knowledge Retrieval System")
    parser.add_argument("--query", "-q", type=str, help="Query the knowledge base")
    parser.add_argument("--topic", "-t", type=str, help="Get chunks by topic")
    parser.add_argument("--stats", action="store_true", help="Show stats")

    args = parser.parse_args()

    retriever = KnowledgeRetriever()

    if args.stats:
        stats = retriever.get_stats()
        print("\nKnowledge Retriever Statistics:")
        print(f"  Total chunks: {stats['total_chunks']}")
        print(f"  TF-IDF indexed: {stats['indexed']}")
        print("\n  Topics:")
        for topic, count in sorted(stats['topic_distribution'].items(), key=lambda x: -x[1]):
            print(f"    {topic}: {count} chunks")

    elif args.query:
        results = retriever.query(args.query)
        print(f"\nResults for: '{args.query}'\n")
        for i, r in enumerate(results, 1):
            print(f"{i}. [{r.relevance_score:.2f}] {r.title}")
            print(f"   Topics: {', '.join(r.topics)}")
            print(f"   {r.content[:200]}...")
            print()

    elif args.topic:
        results = retriever.query_by_topic(args.topic)
        print(f"\nChunks for topic: '{args.topic}'\n")
        for i, r in enumerate(results, 1):
            print(f"{i}. {r.title}")
            print(f"   {r.content[:200]}...")
            print()
    else:
        parser.print_help()
