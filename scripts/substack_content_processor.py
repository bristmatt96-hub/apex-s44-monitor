"""
Substack Content Processor
Handles different Substack sources with appropriate strategies:

- Capital Flows: Auto-download tutorials/educational content → knowledge base
- Le Shrub: Evaluate trade ideas → agent decides whether to act

This replaces blind copying with intelligent processing.
"""

import os
import sys
import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")


class ContentType(Enum):
    """Type of Substack content"""
    TUTORIAL = "tutorial"           # Educational - auto-ingest
    MARKET_ANALYSIS = "analysis"    # Background info - auto-ingest
    TRADE_IDEA = "trade_idea"       # Requires evaluation before acting
    NEWS = "news"                   # Informational - auto-ingest


@dataclass
class SubstackArticle:
    """Processed Substack article"""
    title: str
    author: str
    source: str  # 'capital_flows' or 'le_shrub'
    content: str
    published: datetime
    content_type: ContentType
    tickers: List[str]
    trade_thesis: Optional[str] = None  # For trade ideas
    confidence_signals: List[str] = None  # Why this might be good


class ContentClassifier:
    """
    Classifies Substack content to determine how to handle it.
    """

    # Keywords that indicate educational/tutorial content (auto-ingest)
    TUTORIAL_KEYWORDS = [
        'how to', 'guide', 'tutorial', 'explained', 'introduction',
        'basics', 'fundamentals', 'primer', 'learning', 'education',
        'what is', 'understanding', 'framework', 'methodology',
        'backtesting', 'strategy development', 'risk management basics'
    ]

    # Keywords that indicate a specific trade idea (requires evaluation)
    TRADE_IDEA_KEYWORDS = [
        'buy', 'sell', 'long', 'short', 'position', 'trade',
        'entry', 'exit', 'target', 'stop loss', 'risk/reward',
        'i\'m buying', 'i\'m selling', 'opening a position',
        'trade idea', 'setup', 'opportunity', 'play'
    ]

    # Keywords for market analysis (auto-ingest as background)
    ANALYSIS_KEYWORDS = [
        'market update', 'weekly review', 'macro', 'flows',
        'positioning', 'sentiment', 'outlook', 'analysis',
        'review', 'summary', 'overview'
    ]

    @classmethod
    def classify(cls, title: str, content: str, source: str) -> ContentType:
        """Classify content type based on title and content"""
        text = (title + " " + content[:1000]).lower()

        # Check for tutorial content first (highest priority for Capital Flows)
        if source == 'capital_flows':
            for keyword in cls.TUTORIAL_KEYWORDS:
                if keyword in text:
                    return ContentType.TUTORIAL

        # Check for specific trade ideas
        trade_signals = sum(1 for kw in cls.TRADE_IDEA_KEYWORDS if kw in text)
        if trade_signals >= 2:  # Multiple trade-related keywords
            return ContentType.TRADE_IDEA

        # Check for market analysis
        for keyword in cls.ANALYSIS_KEYWORDS:
            if keyword in text:
                return ContentType.MARKET_ANALYSIS

        # Default based on source
        if source == 'le_shrub':
            return ContentType.TRADE_IDEA  # Le Shrub often has trade ideas
        return ContentType.MARKET_ANALYSIS


class TradeIdeaEvaluator:
    """
    Evaluates trade ideas from Substacks like Le Shrub.
    The agent doesn't blindly copy - it decides if the idea makes sense.
    """

    def __init__(self):
        self.evaluation_criteria = [
            "risk_reward_ratio",
            "aligns_with_market_regime",
            "position_size_reasonable",
            "clear_thesis",
            "defined_exit_strategy"
        ]

    def extract_trade_thesis(self, content: str) -> Dict[str, Any]:
        """Extract the core trade thesis from content"""
        thesis = {
            'direction': None,  # long/short
            'asset': None,
            'timeframe': None,
            'entry_trigger': None,
            'target': None,
            'stop_loss': None,
            'rationale': None,
            'risks': []
        }

        content_lower = content.lower()

        # Detect direction
        if any(w in content_lower for w in ['long', 'buy', 'bullish', 'calls']):
            thesis['direction'] = 'long'
        elif any(w in content_lower for w in ['short', 'sell', 'bearish', 'puts']):
            thesis['direction'] = 'short'

        # Extract tickers mentioned
        import re
        tickers = re.findall(r'\$([A-Z]{1,5})\b', content.upper())
        if tickers:
            thesis['asset'] = tickers[0]  # Primary ticker

        return thesis

    def evaluate(self, article: SubstackArticle, market_context: Dict = None) -> Dict[str, Any]:
        """
        Evaluate whether a trade idea should be acted upon.

        Returns evaluation with recommendation.
        """
        evaluation = {
            'article_title': article.title,
            'source': article.source,
            'trade_thesis': self.extract_trade_thesis(article.content),
            'checks': {},
            'score': 0,
            'max_score': 5,
            'recommendation': 'REVIEW',  # IGNORE, REVIEW, CONSIDER, ACT
            'reasoning': []
        }

        thesis = evaluation['trade_thesis']

        # Check 1: Clear direction
        if thesis['direction']:
            evaluation['checks']['clear_direction'] = True
            evaluation['score'] += 1
            evaluation['reasoning'].append(f"Clear {thesis['direction']} bias identified")
        else:
            evaluation['checks']['clear_direction'] = False
            evaluation['reasoning'].append("No clear directional bias - informational only")

        # Check 2: Specific asset identified
        if thesis['asset']:
            evaluation['checks']['specific_asset'] = True
            evaluation['score'] += 1
            evaluation['reasoning'].append(f"Specific asset: {thesis['asset']}")
        else:
            evaluation['checks']['specific_asset'] = False
            evaluation['reasoning'].append("No specific tradeable asset mentioned")

        # Check 3: Author track record (Le Shrub generally has interesting ideas)
        if article.source == 'le_shrub':
            evaluation['checks']['reputable_source'] = True
            evaluation['score'] += 1
            evaluation['reasoning'].append("Le Shrub has track record of interesting macro plays")

        # Check 4: Content length (more detailed = more conviction)
        if len(article.content) > 2000:
            evaluation['checks']['detailed_analysis'] = True
            evaluation['score'] += 1
            evaluation['reasoning'].append("Detailed analysis provided")

        # Check 5: Multiple supporting arguments
        supporting_keywords = ['because', 'therefore', 'data shows', 'historically', 'positioning']
        supports = sum(1 for kw in supporting_keywords if kw in article.content.lower())
        if supports >= 2:
            evaluation['checks']['supported_thesis'] = True
            evaluation['score'] += 1
            evaluation['reasoning'].append(f"Multiple supporting arguments ({supports} found)")

        # Generate recommendation
        score_pct = evaluation['score'] / evaluation['max_score']
        if score_pct >= 0.8:
            evaluation['recommendation'] = 'CONSIDER'
            evaluation['action'] = "Flag for review - strong thesis with clear setup"
        elif score_pct >= 0.6:
            evaluation['recommendation'] = 'REVIEW'
            evaluation['action'] = "Worth reviewing - has merit but needs validation"
        elif score_pct >= 0.4:
            evaluation['recommendation'] = 'MONITOR'
            evaluation['action'] = "Monitor only - thesis unclear or missing details"
        else:
            evaluation['recommendation'] = 'IGNORE'
            evaluation['action'] = "Informational only - no actionable trade idea"

        return evaluation


class SubstackContentProcessor:
    """
    Main processor that handles Substack content intelligently.
    """

    def __init__(self):
        self.classifier = ContentClassifier()
        self.evaluator = TradeIdeaEvaluator()
        self.knowledge_dir = project_root / "knowledge" / "substack_articles"
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)
        self.evaluations_dir = project_root / "knowledge" / "trade_evaluations"
        self.evaluations_dir.mkdir(parents=True, exist_ok=True)

    def process_article(self, article: SubstackArticle) -> Dict[str, Any]:
        """
        Process an article based on its type.

        - Tutorials/Analysis: Auto-save to knowledge base
        - Trade Ideas: Evaluate and save evaluation
        """
        result = {
            'article': article.title,
            'source': article.source,
            'content_type': article.content_type.value,
            'action_taken': None,
            'saved_to': None
        }

        if article.content_type in [ContentType.TUTORIAL, ContentType.MARKET_ANALYSIS, ContentType.NEWS]:
            # Auto-ingest educational content
            filepath = self._save_to_knowledge_base(article)
            result['action_taken'] = 'AUTO_INGESTED'
            result['saved_to'] = str(filepath)
            print(f"  ✅ Auto-ingested: {article.title[:50]}...")

        elif article.content_type == ContentType.TRADE_IDEA:
            # Evaluate trade idea
            evaluation = self.evaluator.evaluate(article)
            eval_filepath = self._save_evaluation(article, evaluation)
            result['action_taken'] = 'EVALUATED'
            result['evaluation'] = evaluation
            result['saved_to'] = str(eval_filepath)

            rec = evaluation['recommendation']
            print(f"  🔍 Evaluated: {article.title[:40]}... → {rec}")
            print(f"     Score: {evaluation['score']}/{evaluation['max_score']}")
            print(f"     Action: {evaluation['action']}")

        return result

    def _save_to_knowledge_base(self, article: SubstackArticle) -> Path:
        """Save article to knowledge base"""
        date_str = article.published.strftime('%Y-%m-%d')
        safe_title = "".join(c for c in article.title if c.isalnum() or c in ' -_')[:50]
        filename = f"{date_str}_{article.source}_{safe_title}.txt".replace(' ', '_')
        filepath = self.knowledge_dir / filename

        content = f"""# {article.title}
# Source: {article.source}
# Type: {article.content_type.value}
# Date: {article.published.isoformat()}

{article.content}
"""
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

        # Try to index
        try:
            from knowledge.text_indexer import index_text_file
            index_text_file(str(filepath), f"substack_{article.source}")
        except:
            pass

        return filepath

    def _save_evaluation(self, article: SubstackArticle, evaluation: Dict) -> Path:
        """Save trade idea evaluation"""
        date_str = article.published.strftime('%Y-%m-%d')
        safe_title = "".join(c for c in article.title if c.isalnum() or c in ' -_')[:30]
        filename = f"{date_str}_{article.source}_{safe_title}_eval.json".replace(' ', '_')
        filepath = self.evaluations_dir / filename

        output = {
            'article': {
                'title': article.title,
                'source': article.source,
                'published': article.published.isoformat(),
                'content_preview': article.content[:500]
            },
            'evaluation': evaluation,
            'evaluated_at': datetime.now().isoformat()
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2)

        # Also save full article for reference
        article_filepath = self.knowledge_dir / filename.replace('_eval.json', '.txt')
        with open(article_filepath, 'w', encoding='utf-8') as f:
            f.write(f"# {article.title}\n# TRADE IDEA - See evaluation\n\n{article.content}")

        return filepath


def process_from_email_parser():
    """
    Hook into the email parser to process content intelligently.
    """
    from scripts.substack_email_parser import SubstackEmailParser

    processor = SubstackContentProcessor()

    # Get credentials
    email = os.getenv('SUBSTACK_EMAIL')
    password = os.getenv('SUBSTACK_EMAIL_PASSWORD')

    if not email or not password:
        print("Set SUBSTACK_EMAIL and SUBSTACK_EMAIL_PASSWORD in .env")
        return

    # Detect provider
    if 'gmail' in email:
        provider = 'gmail'
    elif any(x in email for x in ['hotmail', 'outlook', 'live']):
        provider = 'outlook'
    else:
        provider = 'gmail'

    parser = SubstackEmailParser(email, password, provider)

    print("\n" + "="*60)
    print("INTELLIGENT SUBSTACK PROCESSOR")
    print("="*60)
    print("Capital Flows tutorials → Auto-ingest to knowledge base")
    print("Le Shrub trade ideas → Evaluate before acting")
    print("="*60 + "\n")

    articles = parser.fetch_substack_emails(days=30, limit=50)

    if not articles:
        print("No new Substack articles found.")
        return

    print(f"Processing {len(articles)} articles...\n")

    results = {'auto_ingested': 0, 'evaluated': 0}

    for article_data in articles:
        # Classify content
        source = article_data['substack']
        content_type = ContentClassifier.classify(
            article_data['subject'],
            article_data['content'],
            source
        )

        # Create article object
        article = SubstackArticle(
            title=article_data['subject'],
            author=source,
            source=source,
            content=article_data['content'],
            published=article_data['date'],
            content_type=content_type,
            tickers=[]  # Could extract these
        )

        # Process
        result = processor.process_article(article)

        if result['action_taken'] == 'AUTO_INGESTED':
            results['auto_ingested'] += 1
        elif result['action_taken'] == 'EVALUATED':
            results['evaluated'] += 1

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"Auto-ingested (tutorials/analysis): {results['auto_ingested']}")
    print(f"Evaluated (trade ideas): {results['evaluated']}")
    print(f"\nKnowledge base: {processor.knowledge_dir}")
    print(f"Evaluations: {processor.evaluations_dir}")


if __name__ == "__main__":
    process_from_email_parser()
