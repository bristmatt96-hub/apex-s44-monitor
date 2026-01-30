"""
Substack Email Parser
Fetches Substack newsletter emails and extracts content for the knowledge base.

Works with Outlook/Hotmail, Gmail, and other IMAP providers.

Usage:
    python scripts/substack_email_parser.py                    # Fetch new emails
    python scripts/substack_email_parser.py --days 30          # Fetch last 30 days
    python scripts/substack_email_parser.py --list             # List available emails
"""

import os
import sys
import re
import imaplib
import email
from email.header import decode_header
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional
import hashlib

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False
    print("Note: Install beautifulsoup4 for better HTML parsing: pip install beautifulsoup4")


# IMAP server settings
IMAP_SERVERS = {
    'outlook': 'outlook.office365.com',
    'hotmail': 'outlook.office365.com',
    'gmail': 'imap.gmail.com',
    'yahoo': 'imap.mail.yahoo.com',
}

# Substacks to look for (sender patterns)
SUBSTACK_SENDERS = {
    'capital_flows': ['capitalflows', 'capital flows', 'capitalflowsresearch'],
    'le_shrub': ['shrub', 'le shrub', 'shrubstack'],
}


class SubstackEmailParser:
    """Parse Substack emails from IMAP mailbox"""

    def __init__(self, email_address: str, password: str, provider: str = 'outlook'):
        self.email_address = email_address
        self.password = password
        self.provider = provider.lower()
        self.imap_server = IMAP_SERVERS.get(self.provider, IMAP_SERVERS['outlook'])
        self.connection = None

        # Output directory
        self.output_dir = project_root / "knowledge" / "substack_articles"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Track processed emails
        self.processed_file = self.output_dir / ".processed_ids.txt"
        self.processed_ids = self._load_processed_ids()

    def _load_processed_ids(self) -> set:
        """Load previously processed email IDs"""
        if self.processed_file.exists():
            with open(self.processed_file, 'r') as f:
                return set(line.strip() for line in f)
        return set()

    def _save_processed_id(self, msg_id: str):
        """Mark an email as processed"""
        self.processed_ids.add(msg_id)
        with open(self.processed_file, 'a') as f:
            f.write(f"{msg_id}\n")

    def connect(self) -> bool:
        """Connect to IMAP server"""
        try:
            print(f"Connecting to {self.imap_server}...")
            self.connection = imaplib.IMAP4_SSL(self.imap_server)
            self.connection.login(self.email_address, self.password)
            print("Connected successfully!")
            return True
        except imaplib.IMAP4.error as e:
            print(f"IMAP login failed: {e}")
            print("\nTroubleshooting:")
            print("1. Check your email/password")
            print("2. If you have 2FA enabled, use an App Password")
            print("3. Make sure IMAP is enabled in your email settings")
            return False
        except Exception as e:
            print(f"Connection error: {e}")
            return False

    def disconnect(self):
        """Disconnect from IMAP server"""
        if self.connection:
            try:
                self.connection.logout()
            except:
                pass

    def _decode_header_value(self, value) -> str:
        """Decode email header value"""
        if value is None:
            return ""
        decoded_parts = decode_header(value)
        result = []
        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                result.append(part.decode(encoding or 'utf-8', errors='replace'))
            else:
                result.append(part)
        return ''.join(result)

    def _extract_html_content(self, html: str) -> str:
        """Extract clean text from HTML email"""
        if BS4_AVAILABLE:
            soup = BeautifulSoup(html, 'html.parser')

            # Remove script and style elements
            for element in soup(['script', 'style', 'head', 'meta', 'link']):
                element.decompose()

            # Get text
            text = soup.get_text(separator='\n', strip=True)
        else:
            # Basic HTML stripping
            text = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<[^>]+>', '\n', text)
            text = re.sub(r'\n\s*\n', '\n\n', text)

        # Clean up
        lines = [line.strip() for line in text.split('\n')]
        lines = [line for line in lines if line]

        # Remove common email footer patterns
        clean_lines = []
        for line in lines:
            # Skip unsubscribe links and footer text
            if any(pattern in line.lower() for pattern in [
                'unsubscribe', 'manage your subscription', 'view in browser',
                'click here to', 'update your preferences', '© 20', 'all rights reserved'
            ]):
                continue
            clean_lines.append(line)

        return '\n'.join(clean_lines)

    def _get_email_body(self, msg) -> str:
        """Extract body from email message"""
        body = ""

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()

                # Prefer HTML for better formatting
                if content_type == 'text/html':
                    payload = part.get_payload(decode=True)
                    if payload:
                        html = payload.decode('utf-8', errors='replace')
                        body = self._extract_html_content(html)
                        break
                elif content_type == 'text/plain' and not body:
                    payload = part.get_payload(decode=True)
                    if payload:
                        body = payload.decode('utf-8', errors='replace')
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                content_type = msg.get_content_type()
                text = payload.decode('utf-8', errors='replace')
                if content_type == 'text/html':
                    body = self._extract_html_content(text)
                else:
                    body = text

        return body

    def _identify_substack(self, sender: str, subject: str) -> Optional[str]:
        """Identify which Substack this email is from"""
        sender_lower = sender.lower()
        subject_lower = subject.lower()

        for substack_id, patterns in SUBSTACK_SENDERS.items():
            for pattern in patterns:
                if pattern in sender_lower or pattern in subject_lower:
                    return substack_id

        # Check for generic Substack emails
        if 'substack' in sender_lower:
            # Try to extract name from sender
            return 'substack_other'

        return None

    def fetch_substack_emails(self, days: int = 7, limit: int = 50) -> List[Dict]:
        """Fetch Substack emails from the last N days"""
        if not self.connection:
            if not self.connect():
                return []

        articles = []

        try:
            # Select inbox
            self.connection.select('INBOX')

            # Search for emails from Substack
            since_date = (datetime.now() - timedelta(days=days)).strftime('%d-%b-%Y')

            # Search for emails containing 'substack' in FROM
            _, message_numbers = self.connection.search(None, f'(SINCE {since_date} FROM "substack")')

            email_ids = message_numbers[0].split()
            print(f"Found {len(email_ids)} Substack emails from last {days} days")

            # Process emails (most recent first)
            for email_id in reversed(email_ids[-limit:]):
                try:
                    # Generate unique ID
                    msg_hash = hashlib.md5(email_id).hexdigest()[:12]

                    if msg_hash in self.processed_ids:
                        continue

                    # Fetch email
                    _, msg_data = self.connection.fetch(email_id, '(RFC822)')

                    for response_part in msg_data:
                        if isinstance(response_part, tuple):
                            msg = email.message_from_bytes(response_part[1])

                            # Extract headers
                            subject = self._decode_header_value(msg['subject'])
                            sender = self._decode_header_value(msg['from'])
                            date_str = msg['date']

                            # Parse date
                            try:
                                from email.utils import parsedate_to_datetime
                                date = parsedate_to_datetime(date_str)
                            except:
                                date = datetime.now()

                            # Identify Substack
                            substack_id = self._identify_substack(sender, subject)
                            if not substack_id:
                                continue

                            # Extract body
                            body = self._get_email_body(msg)

                            if body and len(body) > 100:  # Minimum content length
                                articles.append({
                                    'id': msg_hash,
                                    'subject': subject,
                                    'sender': sender,
                                    'date': date,
                                    'substack': substack_id,
                                    'content': body
                                })
                                print(f"  Found: {subject[:60]}...")

                except Exception as e:
                    print(f"  Error processing email: {e}")
                    continue

        except Exception as e:
            print(f"Error fetching emails: {e}")

        return articles

    def save_article(self, article: Dict) -> Path:
        """Save article to knowledge base"""
        # Create filename from date and subject
        date_str = article['date'].strftime('%Y-%m-%d')
        safe_subject = re.sub(r'[^\w\s-]', '', article['subject'])[:50].strip()
        safe_subject = re.sub(r'\s+', '_', safe_subject)

        filename = f"{date_str}_{article['substack']}_{safe_subject}.txt"
        filepath = self.output_dir / filename

        # Write content
        content = f"""# {article['subject']}
# Source: {article['substack']}
# Date: {article['date'].isoformat()}
# Sender: {article['sender']}

{article['content']}
"""

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

        # Mark as processed
        self._save_processed_id(article['id'])

        return filepath

    def index_article(self, filepath: Path):
        """Index article in knowledge base"""
        try:
            from knowledge.text_indexer import index_text_file
            doc_id = index_text_file(str(filepath), "substack")
            print(f"  Indexed: {filepath.name} (ID: {doc_id})")
            return doc_id
        except ImportError:
            print(f"  Saved (not indexed): {filepath.name}")
            return None
        except Exception as e:
            print(f"  Saved (indexing failed: {e})")
            return None


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Fetch Substack emails')
    parser.add_argument('--days', type=int, default=7, help='Fetch emails from last N days')
    parser.add_argument('--limit', type=int, default=50, help='Max emails to process')
    parser.add_argument('--list', action='store_true', help='List emails without saving')
    args = parser.parse_args()

    # Get credentials from environment
    email_address = os.getenv('SUBSTACK_EMAIL')
    email_password = os.getenv('SUBSTACK_EMAIL_PASSWORD')

    if not email_address or not email_password:
        print("ERROR: Set SUBSTACK_EMAIL and SUBSTACK_EMAIL_PASSWORD in .env")
        print("\nExample:")
        print("  SUBSTACK_EMAIL=your_email@hotmail.com")
        print("  SUBSTACK_EMAIL_PASSWORD=your_app_password")
        print("\nNote: If you have 2FA, use an App Password from:")
        print("  https://account.microsoft.com/security")
        sys.exit(1)

    # Detect provider
    if 'hotmail' in email_address or 'outlook' in email_address or 'live' in email_address:
        provider = 'outlook'
    elif 'gmail' in email_address:
        provider = 'gmail'
    else:
        provider = 'outlook'  # Default

    print(f"\n{'='*60}")
    print(f"SUBSTACK EMAIL PARSER")
    print(f"{'='*60}")
    print(f"Email: {email_address}")
    print(f"Provider: {provider}")
    print(f"Days: {args.days}")
    print(f"{'='*60}\n")

    parser_instance = SubstackEmailParser(email_address, email_password, provider)

    try:
        articles = parser_instance.fetch_substack_emails(days=args.days, limit=args.limit)

        if not articles:
            print("\nNo new Substack emails found.")
            return

        print(f"\nFound {len(articles)} new articles")

        if args.list:
            print("\nArticles:")
            for art in articles:
                print(f"  [{art['date'].strftime('%Y-%m-%d')}] {art['substack']}: {art['subject'][:50]}")
            return

        # Save and index articles
        print("\nSaving articles...")
        for article in articles:
            filepath = parser_instance.save_article(article)
            parser_instance.index_article(filepath)

        print(f"\nDone! Articles saved to: {parser_instance.output_dir}")
        print("\nNext steps:")
        print("  1. Review articles in knowledge/substack_articles/")
        print("  2. Commit to git: git add knowledge/substack_articles/ && git commit -m 'Add Substack articles'")

    finally:
        parser_instance.disconnect()


if __name__ == "__main__":
    main()
