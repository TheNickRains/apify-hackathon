"""
GROK Wallet Doxxer - Apify Actor Entry Point

Searches Twitter/X for wallet addresses using xAI's GROK with x_search tool.
Identifies wallet owners with confidence scores.

Production features:
- Checkpoint/resume using Apify Key-Value Store
- Batch processing for large datasets (33k+ wallets)
- Progress persistence across Actor restarts
"""

import os
import asyncio
import logging
import hashlib
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

# Checkpoint configuration
CHECKPOINT_KEY = "wallet_checkpoint"
CHECKPOINT_INTERVAL = 10  # Save checkpoint every N wallets


def generate_input_hash(wallets: list[str]) -> str:
    """Generate a hash of the input wallet list for checkpoint validation."""
    content = ",".join(sorted(wallets))
    return hashlib.md5(content.encode()).hexdigest()[:12]


async def load_checkpoint() -> dict:
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


async def save_checkpoint(
    processed_wallets: set,
    stats: dict,
    input_hash: str,
    total_wallets: int
):
    """Save checkpoint to Key-Value Store."""
    try:
        store = await Actor.open_key_value_store()
        checkpoint = {
            'processed_wallets': list(processed_wallets),
            'processed_count': len(processed_wallets),
            'total_wallets': total_wallets,
            'input_hash': input_hash,
            'stats': stats
        }
        await store.set_value(CHECKPOINT_KEY, checkpoint)
        Actor.log.debug(f"Checkpoint saved: {len(processed_wallets)} wallets")
    except Exception as e:
        Actor.log.warning(f"Could not save checkpoint: {e}")


async def clear_checkpoint():
    """Clear checkpoint after successful completion."""
    try:
        store = await Actor.open_key_value_store()
        await store.set_value(CHECKPOINT_KEY, None)
        Actor.log.info("Checkpoint cleared (run complete)")
    except Exception as e:
        Actor.log.warning(f"Could not clear checkpoint: {e}")


async def main():
    """Main Actor entry point."""
    async with Actor:
        # Get input
        actor_input = await Actor.get_input() or {}
        
        # Extract wallet input (three ways to provide wallets)
        wallet_addresses = actor_input.get('walletAddresses', [])
        wallet_text = actor_input.get('walletText', '')
        input_file = actor_input.get('inputFile')
        
        # Production options
        batch_limit = actor_input.get('batchLimit', 0)  # 0 = no limit
        resume_from_checkpoint = actor_input.get('resumeFromCheckpoint', True)
        clear_previous_checkpoint = actor_input.get('clearCheckpoint', False)
        
        # Get API key from environment variable (set in Apify Console by Actor owner)
        xai_api_key = os.environ.get('XAI_API_KEY')
        if not xai_api_key:
            raise ValueError(
                "XAI_API_KEY environment variable not configured. "
                "Please contact the Actor owner."
            )
        
        Actor.log.info("=" * 60)
        Actor.log.info("GROK Wallet Doxxer - Production Mode")
        Actor.log.info("=" * 60)
        Actor.log.info(f"Model: {GROK_MODEL}, Max concurrent: {MAX_CONCURRENT}")
        
        # Clear checkpoint if requested
        if clear_previous_checkpoint:
            await clear_checkpoint()
            Actor.log.info("Previous checkpoint cleared as requested")
        
        # Parse wallet addresses from various input sources
        Actor.log.info("Parsing input...")
        try:
            all_wallets = await parse_input(
                wallet_addresses=wallet_addresses,
                wallet_text=wallet_text,
                input_file=input_file,
                wallet_column=WALLET_COLUMN
            )
        except Exception as e:
            Actor.log.error(f"Failed to parse input: {e}")
            raise
        
        if not all_wallets:
            Actor.log.warning("No valid wallet addresses found in input.")
            Actor.log.info(
                "Provide wallet addresses via 'walletAddresses' (JSON array), "
                "'walletText' (paste), or 'inputFile' (URL)."
            )
            return
        
        Actor.log.info(f"Total wallet addresses: {len(all_wallets)}")
        
        # Generate input hash for checkpoint validation
        input_hash = generate_input_hash(all_wallets)
        Actor.log.info(f"Input hash: {input_hash}")
        
        # Load checkpoint and determine which wallets to process
        processed_wallets = set()
        stats = {
            'total': len(all_wallets),
            'processed': 0,
            'posts_found': 0,
            'handles_identified': 0,
            'errors': 0,
            'skipped': 0
        }
        
        if resume_from_checkpoint:
            checkpoint = await load_checkpoint()
            if checkpoint:
                # Validate checkpoint is for same input
                if checkpoint.get('input_hash') == input_hash:
                    processed_wallets = set(checkpoint.get('processed_wallets', []))
                    prev_stats = checkpoint.get('stats', {})
                    stats['posts_found'] = prev_stats.get('posts_found', 0)
                    stats['handles_identified'] = prev_stats.get('handles_identified', 0)
                    stats['errors'] = prev_stats.get('errors', 0)
                    Actor.log.info(f"Resuming from checkpoint: {len(processed_wallets)} already processed")
                else:
                    Actor.log.warning("Checkpoint input hash mismatch - starting fresh")
                    Actor.log.info(f"  Checkpoint hash: {checkpoint.get('input_hash')}")
                    Actor.log.info(f"  Current hash: {input_hash}")
        
        # Filter out already processed wallets
        wallets_to_process = [w for w in all_wallets if w not in processed_wallets]
        stats['skipped'] = len(processed_wallets)
        
        Actor.log.info(f"Wallets to process: {len(wallets_to_process)}")
        Actor.log.info(f"Already processed: {len(processed_wallets)}")
        
        # Apply batch limit if specified
        if batch_limit > 0 and len(wallets_to_process) > batch_limit:
            Actor.log.info(f"Batch limit: {batch_limit} wallets")
            wallets_to_process = wallets_to_process[:batch_limit]
            Actor.log.info(f"Processing {len(wallets_to_process)} wallets this run")
        
        if not wallets_to_process:
            Actor.log.info("All wallets already processed!")
            await clear_checkpoint()
            return
        
        # Initialize the wallet searcher
        searcher = GrokWalletSearcher(
            api_key=xai_api_key,
            model=GROK_MODEL,
            max_concurrent=MAX_CONCURRENT,
            rate_limit_delay=RATE_LIMIT_DELAY
        )
        
        # Counter for checkpoint saving
        checkpoint_counter = 0
        
        async def on_result(result: SearchResult):
            """Push each result to the dataset and update checkpoint."""
            nonlocal checkpoint_counter
            
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
            
            # Update tracking
            processed_wallets.add(result.wallet)
            stats['processed'] += 1
            if result.post_exists:
                stats['posts_found'] += 1
            if result.twitter_handle:
                stats['handles_identified'] += 1
            if result.error:
                stats['errors'] += 1
            
            # Save checkpoint periodically
            checkpoint_counter += 1
            if checkpoint_counter % CHECKPOINT_INTERVAL == 0:
                await save_checkpoint(processed_wallets, stats, input_hash, len(all_wallets))
        
        def on_progress(current: int, total: int):
            """Log progress updates."""
            overall_processed = len(processed_wallets)
            overall_total = len(all_wallets)
            percent = (overall_processed / overall_total) * 100
            Actor.log.info(
                f"Progress: {overall_processed}/{overall_total} ({percent:.1f}%) "
                f"[This run: {current}/{total}]"
            )
        
        # Process wallets
        Actor.log.info("Starting wallet searches...")
        try:
            results = await searcher.search_wallets(
                wallets=wallets_to_process,
                on_result=on_result,
                on_progress=on_progress
            )
            
            # Save final checkpoint
            await save_checkpoint(processed_wallets, stats, input_hash, len(all_wallets))
            
        except Exception as e:
            # Save checkpoint on error so we can resume
            Actor.log.error(f"Error during processing: {e}")
            await save_checkpoint(processed_wallets, stats, input_hash, len(all_wallets))
            raise
        
        # Log final statistics
        Actor.log.info("=" * 60)
        Actor.log.info("RUN COMPLETE")
        Actor.log.info("=" * 60)
        Actor.log.info(f"This run processed: {len(results)}")
        Actor.log.info(f"Total processed: {len(processed_wallets)}/{len(all_wallets)}")
        Actor.log.info(f"Posts found: {stats['posts_found']}")
        Actor.log.info(f"Twitter handles identified: {stats['handles_identified']}")
        Actor.log.info(f"Errors: {stats['errors']}")
        
        # Calculate success rate
        if stats['processed'] > 0:
            hit_rate = (stats['posts_found'] / len(processed_wallets)) * 100
            Actor.log.info(f"Hit rate: {hit_rate:.1f}%")
        
        # Check if all wallets processed
        if len(processed_wallets) >= len(all_wallets):
            Actor.log.info("All wallets processed! Clearing checkpoint.")
            await clear_checkpoint()
        else:
            remaining = len(all_wallets) - len(processed_wallets)
            Actor.log.info(f"Remaining: {remaining} wallets")
            Actor.log.info("Run Actor again to continue processing.")
        
        Actor.log.info("Results saved to default dataset. Export as CSV/JSON from the Apify Console.")


if __name__ == '__main__':
    asyncio.run(main())
