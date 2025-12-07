"""
Wallet Doxxer - Apify Actor Entry Point

Searches Twitter/X for wallet addresses using xAI's GROK with x_search tool.
Identifies wallet owners with confidence scores.
"""

import os
import asyncio
import hashlib
from apify import Actor

from input_parser import parse_input
from wallet_searcher import GrokWalletSearcher, SearchResult

# Configuration constants
GROK_MODEL = "grok-4-fast"
MAX_CONCURRENT = 5
RATE_LIMIT_DELAY = 1
WALLET_COLUMN = "wallet_address"
CHECKPOINT_KEY = "wallet_checkpoint"
CHECKPOINT_INTERVAL = 10


def generate_input_hash(wallets: list[str]) -> str:
    """Generate hash of wallet list for checkpoint validation."""
    content = ",".join(sorted(wallets))
    return hashlib.md5(content.encode()).hexdigest()[:12]


async def load_checkpoint() -> dict | None:
    """Load checkpoint from Key-Value Store."""
    try:
        store = await Actor.open_key_value_store()
        checkpoint = await store.get_value(CHECKPOINT_KEY)
        if checkpoint:
            Actor.log.info(f"Found checkpoint: {checkpoint.get('processed_count', 0)} wallets processed")
            return checkpoint
    except Exception as e:
        Actor.log.warning(f"Could not load checkpoint: {e}")
    return None


async def save_checkpoint(processed_wallets: set, stats: dict, input_hash: str, total: int):
    """Save checkpoint to Key-Value Store."""
    try:
        store = await Actor.open_key_value_store()
        await store.set_value(CHECKPOINT_KEY, {
            'processed_wallets': list(processed_wallets),
            'processed_count': len(processed_wallets),
            'total_wallets': total,
            'input_hash': input_hash,
            'stats': stats
        })
    except Exception as e:
        Actor.log.warning(f"Could not save checkpoint: {e}")


async def clear_checkpoint():
    """Clear checkpoint after successful completion."""
    try:
        store = await Actor.open_key_value_store()
        await store.set_value(CHECKPOINT_KEY, None)
        Actor.log.info("Checkpoint cleared")
    except Exception as e:
        Actor.log.warning(f"Could not clear checkpoint: {e}")


def get_api_key() -> str:
    """Get API key from environment, raise if missing."""
    api_key = os.environ.get('XAI_API_KEY')
    if not api_key:
        raise ValueError("XAI_API_KEY environment variable not configured.")
    return api_key


async def parse_wallets(actor_input: dict) -> list[str]:
    """Parse wallet addresses from actor input."""
    return await parse_input(
        wallet_addresses=actor_input.get('walletAddresses', []),
        wallet_text=actor_input.get('walletText', ''),
        input_file=actor_input.get('inputFile'),
        wallet_column=WALLET_COLUMN
    )


def restore_stats_from_checkpoint(checkpoint: dict, stats: dict):
    """Restore statistics from checkpoint."""
    prev_stats = checkpoint.get('stats', {})
    stats['posts_found'] = prev_stats.get('posts_found', 0)
    stats['handles_identified'] = prev_stats.get('handles_identified', 0)
    stats['errors'] = prev_stats.get('errors', 0)


def apply_batch_limit(wallets: list[str], limit: int) -> list[str]:
    """Apply batch limit to wallet list."""
    if limit > 0 and len(wallets) > limit:
        Actor.log.info(f"Batch limit: {limit} wallets")
        return wallets[:limit]
    return wallets


def log_summary(stats: dict, processed_count: int, total_count: int, results_count: int):
    """Log final run summary."""
    Actor.log.info("=" * 50)
    Actor.log.info("RUN COMPLETE")
    Actor.log.info("=" * 50)
    Actor.log.info(f"This run: {results_count} | Total: {processed_count}/{total_count}")
    Actor.log.info(f"Posts found: {stats['posts_found']} | Handles: {stats['handles_identified']}")
    Actor.log.info(f"Errors: {stats['errors']}")
    
    if processed_count > 0:
        hit_rate = (stats['posts_found'] / processed_count) * 100
        Actor.log.info(f"Hit rate: {hit_rate:.1f}%")


class ResultHandler:
    """Handles results, stats tracking, and checkpointing."""
    
    def __init__(self, processed_wallets: set, stats: dict, input_hash: str, total: int):
        self.processed_wallets = processed_wallets
        self.stats = stats
        self.input_hash = input_hash
        self.total = total
        self.counter = 0
    
    async def handle(self, result: SearchResult):
        """Process a single result."""
        # Build dataset record
        data = {
            'wallet': result.wallet,
            'postExists': result.post_exists,
            'twitterHandle': result.twitter_handle,
            'confidence': result.confidence,
        }
        if result.raw_response and len(result.raw_response) < 1000:
            data['rawResponse'] = result.raw_response
        if result.error:
            data['error'] = result.error
        
        # Push to dataset
        await Actor.push_data(data)
        
        # Update tracking
        self.processed_wallets.add(result.wallet)
        self._update_stats(result)
        
        # Periodic checkpoint
        self.counter += 1
        if self.counter % CHECKPOINT_INTERVAL == 0:
            await save_checkpoint(
                self.processed_wallets, self.stats, self.input_hash, self.total
            )
    
    def _update_stats(self, result: SearchResult):
        """Update statistics from result."""
        self.stats['processed'] += 1
        if result.post_exists:
            self.stats['posts_found'] += 1
        if result.twitter_handle:
            self.stats['handles_identified'] += 1
        if result.error:
            self.stats['errors'] += 1


async def main():
    """Main Actor entry point."""
    async with Actor:
        actor_input = await Actor.get_input() or {}
        api_key = get_api_key()
        
        # Parse options
        batch_limit = actor_input.get('batchLimit', 0)
        resume = actor_input.get('resumeFromCheckpoint', True)
        clear_prev = actor_input.get('clearCheckpoint', False)
        
        Actor.log.info("Wallet Doxxer starting...")
        
        if clear_prev:
            await clear_checkpoint()
        
        # Parse wallets
        all_wallets = await parse_wallets(actor_input)
        if not all_wallets:
            Actor.log.warning("No valid wallet addresses found.")
            return
        
        Actor.log.info(f"Total wallets: {len(all_wallets)}")
        input_hash = generate_input_hash(all_wallets)
        
        # Initialize tracking
        processed_wallets: set[str] = set()
        stats = {'total': len(all_wallets), 'processed': 0, 'posts_found': 0,
                 'handles_identified': 0, 'errors': 0, 'skipped': 0}
        
        # Restore from checkpoint
        if resume:
            checkpoint = await load_checkpoint()
            if checkpoint and checkpoint.get('input_hash') == input_hash:
                processed_wallets = set(checkpoint.get('processed_wallets', []))
                restore_stats_from_checkpoint(checkpoint, stats)
                Actor.log.info(f"Resuming: {len(processed_wallets)} already done")
        
        # Filter and limit
        wallets_to_process = [w for w in all_wallets if w not in processed_wallets]
        wallets_to_process = apply_batch_limit(wallets_to_process, batch_limit)
        
        if not wallets_to_process:
            Actor.log.info("All wallets already processed!")
            await clear_checkpoint()
            return
        
        Actor.log.info(f"Processing: {len(wallets_to_process)} wallets")
        
        # Create searcher and handler
        searcher = GrokWalletSearcher(
            api_key=api_key,
            model=GROK_MODEL,
            max_concurrent=MAX_CONCURRENT,
            rate_limit_delay=RATE_LIMIT_DELAY
        )
        handler = ResultHandler(processed_wallets, stats, input_hash, len(all_wallets))
        
        # Process
        try:
            results = await searcher.search_wallets(
                wallets=wallets_to_process,
                on_result=handler.handle,
                on_progress=lambda c, t: Actor.log.info(f"Progress: {c}/{t}")
            )
            await save_checkpoint(processed_wallets, stats, input_hash, len(all_wallets))
        except Exception as e:
            Actor.log.error(f"Error: {e}")
            await save_checkpoint(processed_wallets, stats, input_hash, len(all_wallets))
            raise
        
        # Summary
        log_summary(stats, len(processed_wallets), len(all_wallets), len(results))
        
        if len(processed_wallets) >= len(all_wallets):
            await clear_checkpoint()
        else:
            Actor.log.info(f"Remaining: {len(all_wallets) - len(processed_wallets)}. Run again to continue.")


if __name__ == '__main__':
    asyncio.run(main())
