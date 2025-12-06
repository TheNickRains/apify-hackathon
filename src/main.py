"""
GROK Wallet Doxxer - Apify Actor Entry Point

Searches Twitter/X for wallet addresses using xAI's GROK with x_search tool.
Identifies wallet owners with confidence scores.
"""

import os
import asyncio
import logging
from apify import Actor

from input_parser import parse_input
from wallet_searcher import GrokWalletSearcher, SearchResult

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Server-side configuration (set via Apify Console environment variables)
GROK_MODEL = "grok-4-fast"
MAX_CONCURRENT = 5
RATE_LIMIT_DELAY = 1
WALLET_COLUMN = "wallet_address"


async def main():
    """Main Actor entry point."""
    async with Actor:
        # Get input (users only provide wallet addresses)
        actor_input = await Actor.get_input() or {}
        
        # Extract wallet input (three ways to provide wallets)
        wallet_addresses = actor_input.get('walletAddresses', [])
        wallet_text = actor_input.get('walletText', '')
        input_file = actor_input.get('inputFile')
        
        # Get API key from environment variable (set in Apify Console by Actor owner)
        xai_api_key = os.environ.get('XAI_API_KEY')
        if not xai_api_key:
            raise ValueError(
                "XAI_API_KEY environment variable not configured. "
                "Please contact the Actor owner."
            )
        
        Actor.log.info("GROK Wallet Doxxer starting...")
        Actor.log.info(f"Model: {GROK_MODEL}, Max concurrent: {MAX_CONCURRENT}")
        
        # Parse wallet addresses from various input sources
        Actor.log.info("Parsing input...")
        try:
            wallets = await parse_input(
                wallet_addresses=wallet_addresses,
                wallet_text=wallet_text,
                input_file=input_file,
                wallet_column=WALLET_COLUMN
            )
        except Exception as e:
            Actor.log.error(f"Failed to parse input: {e}")
            raise
        
        if not wallets:
            Actor.log.warning("No valid wallet addresses found in input.")
            Actor.log.info(
                "Provide wallet addresses via 'walletAddresses' (JSON array) "
                "or 'inputFile' (URL to CSV/JSON/text file)."
            )
            return
        
        Actor.log.info(f"Found {len(wallets)} wallet addresses to process")
        
        # Initialize the wallet searcher
        searcher = GrokWalletSearcher(
            api_key=xai_api_key,
            model=GROK_MODEL,
            max_concurrent=MAX_CONCURRENT,
            rate_limit_delay=RATE_LIMIT_DELAY
        )
        
        # Track statistics
        stats = {
            'total': len(wallets),
            'processed': 0,
            'posts_found': 0,
            'handles_identified': 0,
            'errors': 0
        }
        
        async def on_result(result: SearchResult):
            """Push each result to the dataset as it completes."""
            # Convert to dataset format
            data = {
                'wallet': result.wallet,
                'postExists': result.post_exists,
                'twitterHandle': result.twitter_handle,
                'confidence': result.confidence,
            }
            
            # Only include raw response if there's meaningful content
            if result.raw_response and len(result.raw_response) < 1000:
                data['rawResponse'] = result.raw_response
            
            if result.error:
                data['error'] = result.error
            
            # Push to default dataset
            await Actor.push_data(data)
            
            # Update stats
            stats['processed'] += 1
            if result.post_exists:
                stats['posts_found'] += 1
            if result.twitter_handle:
                stats['handles_identified'] += 1
            if result.error:
                stats['errors'] += 1
        
        def on_progress(current: int, total: int):
            """Log progress updates."""
            percent = (current / total) * 100
            Actor.log.info(f"Progress: {current}/{total} ({percent:.1f}%)")
        
        # Process all wallets
        Actor.log.info("Starting wallet searches...")
        results = await searcher.search_wallets(
            wallets=wallets,
            on_result=on_result,
            on_progress=on_progress
        )
        
        # Log final statistics
        Actor.log.info("=" * 50)
        Actor.log.info("SEARCH COMPLETE")
        Actor.log.info("=" * 50)
        Actor.log.info(f"Total wallets processed: {stats['processed']}")
        Actor.log.info(f"Posts found: {stats['posts_found']}")
        Actor.log.info(f"Twitter handles identified: {stats['handles_identified']}")
        Actor.log.info(f"Errors: {stats['errors']}")
        
        # Calculate success rate
        if stats['processed'] > 0:
            hit_rate = (stats['posts_found'] / stats['processed']) * 100
            Actor.log.info(f"Hit rate: {hit_rate:.1f}%")
        
        Actor.log.info("Results saved to default dataset. Export as CSV/JSON from the Apify Console.")


if __name__ == '__main__':
    asyncio.run(main())
