"""
GROK-powered wallet search using x.ai SDK with x_search tool.
Searches Twitter/X for wallet addresses and extracts usernames with confidence scores.
"""

import re
import asyncio
import time
import logging
from collections import deque
from typing import Any, Optional, Callable, Awaitable, Union
from dataclasses import dataclass

# Type alias for async or sync callbacks
AsyncCallback = Callable[[Any], Awaitable[None]]
SyncCallback = Callable[[Any], None]
ResultCallback = Optional[Union[AsyncCallback, SyncCallback]]

from xai_sdk import Client
from xai_sdk.chat import user
from xai_sdk.tools import x_search

# Try to import grpc for better error handling
try:
    import grpc
    GRPC_AVAILABLE = True
except ImportError:
    GRPC_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Result from a wallet search."""
    wallet: str
    post_exists: bool
    twitter_handle: Optional[str]
    confidence: str
    raw_response: str = ""
    error: Optional[str] = None


class GrokWalletSearcher:
    """Search Twitter/X for wallet addresses using GROK's x_search tool."""
    
    def __init__(
        self,
        api_key: str,
        model: str = "grok-4-fast",
        max_concurrent: int = 5,
        rate_limit_delay: int = 1,
        shared_semaphore: Optional[asyncio.Semaphore] = None
    ):
        """
        Initialize GROK client.
        
        Args:
            api_key: x.ai API key
            model: GROK model to use
            max_concurrent: Maximum concurrent requests
            rate_limit_delay: Base delay between requests
            shared_semaphore: Optional shared semaphore for concurrency control
        """
        self.client = Client(api_key=api_key)
        self.model = model
        self.max_concurrent = max_concurrent
        self.rate_limit_delay = rate_limit_delay
        
        # Use shared semaphore if provided, otherwise create new one
        self.semaphore = shared_semaphore or asyncio.Semaphore(max_concurrent)
        
        # Rate limiting tracking
        self.request_times: deque = deque()
        self.rate_limit_window = 60  # 60 second window
        self.max_requests_per_window = 50
        self.consecutive_rate_limits = 0
        
        logger.info(f"Initialized GrokWalletSearcher with model={model}, max_concurrent={max_concurrent}")
    
    async def wait_for_rate_limit_window(self):
        """Wait if we're approaching rate limit."""
        now = time.time()
        
        # Remove requests outside the window
        while self.request_times and self.request_times[0] < now - self.rate_limit_window:
            self.request_times.popleft()
        
        # If we're at the limit, wait
        if len(self.request_times) >= self.max_requests_per_window:
            wait_time = self.rate_limit_window - (now - self.request_times[0])
            if wait_time > 0:
                logger.info(f"Approaching rate limit, waiting {wait_time:.1f} seconds...")
                await asyncio.sleep(wait_time)
        
        # Record this request
        self.request_times.append(time.time())
    
    async def handle_rate_limit_error(self, attempt: int, max_retries: int):
        """Handle rate limit with exponential backoff."""
        self.consecutive_rate_limits += 1
        
        # Exponential backoff: 60s, 120s, 240s (capped at 5 minutes)
        base_delay = 60
        backoff_delay = min(base_delay * (2 ** (attempt - 1)), 300)
        
        # If multiple consecutive rate limits, increase delay
        if self.consecutive_rate_limits > 1:
            backoff_delay *= min(self.consecutive_rate_limits, 3)
        
        logger.warning(
            f"Rate limit detected (attempt {attempt}/{max_retries}, "
            f"consecutive: {self.consecutive_rate_limits}). "
            f"Waiting {backoff_delay} seconds..."
        )
        await asyncio.sleep(backoff_delay)
    
    def extract_username(self, content: str) -> Optional[str]:
        """Extract Twitter username from GROK response using regex."""
        patterns = [
            r'username[:\s]+@?([A-Za-z0-9_]{1,15})',
            r'@([A-Za-z0-9_]{1,15})',
            r'handle[:\s]+@?([A-Za-z0-9_]{1,15})',
            r'twitter[:\s]+@?([A-Za-z0-9_]{1,15})',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                username = match.group(1)
                if 1 <= len(username) <= 15 and re.match(r'^[A-Za-z0-9_]+$', username):
                    return username
        
        return None
    
    def extract_confidence_level(self, content: str) -> Optional[str]:
        """Extract confidence level from GROK response (High, Medium, Low, None)."""
        content_lower = content.lower()
        
        # Look for confidence level keywords
        if re.search(r'\b(high|strong|clear|definite|certain)\b', content_lower):
            return "High"
        elif re.search(r'\b(medium|moderate|somewhat|partial)\b', content_lower):
            return "Medium"
        elif re.search(r'\b(low|weak|minimal|uncertain)\b', content_lower):
            return "Low"
        elif re.search(r'\b(none|no|false|not found)\b', content_lower):
            return "None"
        
        # Check for explicit format
        confidence_patterns = [
            r'confidence[:\s]+(high|medium|low|none)',
            r'confidence[:\s]+(strong|moderate|weak|none)',
            r'level[:\s]+(high|medium|low|none)',
        ]
        
        for pattern in confidence_patterns:
            match = re.search(pattern, content_lower)
            if match:
                level = match.group(1).lower()
                if level in ["high", "strong"]:
                    return "High"
                elif level in ["medium", "moderate"]:
                    return "Medium"
                elif level in ["low", "weak"]:
                    return "Low"
                elif level == "none":
                    return "None"
        
        return None
    
    def _is_rate_limit_error(self, error: Exception) -> bool:
        """Check if an exception is a rate limit error."""
        error_str = str(error).lower()
        
        # Check for gRPC RESOURCE_EXHAUSTED error
        if GRPC_AVAILABLE:
            try:
                if hasattr(error, 'code') and error.code() == grpc.StatusCode.RESOURCE_EXHAUSTED:
                    return True
            except (AttributeError, TypeError):
                pass
        
        # String-based detection
        rate_limit_indicators = ["rate limit", "429", "too many requests", "resource_exhausted"]
        return any(indicator in error_str for indicator in rate_limit_indicators)
    
    async def agent_check_post_exists(self, wallet: str, max_retries: int = 3) -> tuple[bool, str]:
        """Agent 1: Check if any post exists containing the wallet address."""
        await self.wait_for_rate_limit_window()
        
        query = (
            f'Search X for any posts containing the exact phrase "{wallet}". '
            'Respond with only "true" if any post exists, or "false" if no posts are found. '
            'Do not provide any other information.'
        )
        
        for attempt in range(max_retries):
            try:
                logger.debug(f"Agent 1 - Attempt {attempt + 1}/{max_retries}...")
                
                chat = self.client.chat.create(model=self.model, tools=[x_search()])
                chat.append(user(query))
                
                response = chat.sample()
                content = response.content.strip().lower()
                
                # Reset consecutive rate limits on success
                self.consecutive_rate_limits = 0
                
                if "true" in content and "false" not in content:
                    logger.debug("Agent 1: Post exists")
                    return True, content
                elif "false" in content:
                    logger.debug("Agent 1: No posts found")
                    return False, content
                else:
                    logger.warning("Agent 1: Ambiguous response, defaulting to false")
                    return False, content
                
            except Exception as e:
                logger.error(f"Agent 1 error on attempt {attempt + 1}: {e}")
                
                if self._is_rate_limit_error(e):
                    await self.handle_rate_limit_error(attempt + 1, max_retries)
                    continue
                
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2
                    logger.info(f"Waiting {wait_time} seconds before retry...")
                    await asyncio.sleep(wait_time)
                else:
                    return False, f"Error: {str(e)}"
        
        return False, "Max retries exceeded"
    
    async def agent_analyze_ownership(self, wallet: str, max_retries: int = 3) -> dict:
        """Agent 2: Analyze posts to determine wallet ownership and confidence level."""
        await self.wait_for_rate_limit_window()
        
        query = f'''Search X for all posts containing the exact phrase "{wallet}". 

Analyze the context of each post to determine:
1. Who posted it (username/handle)
2. Whether this wallet address belongs to that user (confidence level: high, medium, low, or none)

Confidence level guidelines:
- "High": Clear ownership (user's own post in airdrop thread, wallet sharing, profile bio, explicit ownership statements)
- "Medium": Strong indication (user sharing their wallet for donations, trading, or in context of their activity)
- "Low": Weak indication (user just mentioned or quoted it, minimal context)
- "None": Very weak or no indication of ownership

Return the username and confidence level in this format:
Username: @handle
Confidence: [High|Medium|Low|None]

If multiple posts exist, analyze all of them and provide the highest confidence level with the associated username.'''
        
        for attempt in range(max_retries):
            try:
                logger.debug(f"Agent 2 - Attempt {attempt + 1}/{max_retries}...")
                
                chat = self.client.chat.create(model=self.model, tools=[x_search()])
                chat.append(user(query))
                
                response = chat.sample()
                content = response.content
                
                # Reset consecutive rate limits on success
                self.consecutive_rate_limits = 0
                
                username = self.extract_username(content)
                confidence_level = self.extract_confidence_level(content)
                
                if username:
                    final_confidence = confidence_level if confidence_level else "Medium"
                    logger.debug(f"Agent 2: Username: @{username}, Confidence: {final_confidence}")
                    return {
                        'username': username,
                        'confidence': final_confidence,
                        'raw_response': content
                    }
                else:
                    logger.warning("Agent 2: Could not parse username from response")
                    return {
                        'username': None,
                        'confidence': confidence_level or "Medium",
                        'raw_response': content,
                        'error': 'Could not parse username'
                    }
                
            except Exception as e:
                logger.error(f"Agent 2 error on attempt {attempt + 1}: {e}")
                
                if self._is_rate_limit_error(e):
                    await self.handle_rate_limit_error(attempt + 1, max_retries)
                    continue
                
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2
                    logger.info(f"Waiting {wait_time} seconds before retry...")
                    await asyncio.sleep(wait_time)
                else:
                    return {
                        'username': None,
                        'confidence': None,
                        'raw_response': '',
                        'error': str(e)
                    }
        
        return {
            'username': None,
            'confidence': None,
            'raw_response': '',
            'error': 'Max retries exceeded'
        }
    
    async def search_wallet(self, wallet: str, max_retries: int = 3) -> SearchResult:
        """
        Two-agent workflow: First check if post exists, then analyze ownership.
        
        Args:
            wallet: Wallet address to search
            max_retries: Maximum retry attempts per agent
            
        Returns:
            SearchResult with findings
        """
        logger.info(f"Searching wallet: {wallet[:20]}...")
        
        # Agent 1: Check if post exists
        post_exists, agent1_response = await self.agent_check_post_exists(wallet, max_retries)
        
        if not post_exists:
            logger.info(f"No posts found for wallet: {wallet[:20]}...")
            return SearchResult(
                wallet=wallet,
                post_exists=False,
                twitter_handle=None,
                confidence="None",
                raw_response=agent1_response
            )
        
        # Agent 2: Analyze ownership and confidence
        logger.info(f"Post found for {wallet[:20]}..., analyzing ownership...")
        ownership_result = await self.agent_analyze_ownership(wallet, max_retries)
        
        if ownership_result.get('username'):
            logger.info(
                f"Analysis complete for {wallet[:20]}... - "
                f"@{ownership_result['username']} ({ownership_result['confidence']})"
            )
            return SearchResult(
                wallet=wallet,
                post_exists=True,
                twitter_handle=f"@{ownership_result['username']}",
                confidence=ownership_result['confidence'],
                raw_response=ownership_result.get('raw_response', '')
            )
        else:
            logger.warning(f"Post exists but ownership analysis failed for {wallet[:20]}...")
            return SearchResult(
                wallet=wallet,
                post_exists=True,
                twitter_handle=None,
                confidence=ownership_result.get('confidence', 'Low'),
                raw_response=ownership_result.get('raw_response', ''),
                error=ownership_result.get('error', 'Could not determine ownership')
            )
    
    async def search_wallet_with_semaphore(
        self,
        wallet: str,
        on_result: ResultCallback = None
    ) -> SearchResult:
        """Process a single wallet with semaphore for rate limiting."""
        async with self.semaphore:
            result = await self.search_wallet(wallet)
            if on_result:
                # Support both async and sync callbacks
                callback_result = on_result(result)
                if asyncio.iscoroutine(callback_result):
                    await callback_result
            return result
    
    async def search_wallets(
        self,
        wallets: list[str],
        on_result: ResultCallback = None,
        on_progress: Optional[Callable[[int, int], None]] = None
    ) -> list[SearchResult]:
        """
        Process multiple wallets with parallel execution.
        
        Args:
            wallets: List of wallet addresses to search
            on_result: Callback for each result (for streaming to dataset)
            on_progress: Callback for progress updates (current, total)
            
        Returns:
            List of SearchResults
        """
        if not wallets:
            return []
        
        logger.info(f"Starting search for {len(wallets)} wallets (max concurrent: {self.max_concurrent})")
        
        results = []
        start_time = time.time()
        
        # Process in batches
        batch_size = self.max_concurrent * 2
        
        for batch_start in range(0, len(wallets), batch_size):
            batch = wallets[batch_start:batch_start + batch_size]
            batch_num = batch_start // batch_size + 1
            total_batches = (len(wallets) + batch_size - 1) // batch_size
            
            logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} wallets)...")
            
            # Create tasks for this batch
            tasks = [
                self.search_wallet_with_semaphore(wallet, on_result)
                for wallet in batch
            ]
            
            # Process batch in parallel
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results
            for i, result in enumerate(batch_results):
                if isinstance(result, Exception):
                    logger.error(f"Error processing wallet: {result}")
                    # Create error result
                    error_result = SearchResult(
                        wallet=batch[i],
                        post_exists=False,
                        twitter_handle=None,
                        confidence="None",
                        error=str(result)
                    )
                    results.append(error_result)
                    if on_result:
                        # Support both async and sync callbacks
                        callback_result = on_result(error_result)
                        if asyncio.iscoroutine(callback_result):
                            await callback_result
                else:
                    results.append(result)
            
            # Progress callback
            if on_progress:
                on_progress(min(batch_start + batch_size, len(wallets)), len(wallets))
            
            # Small delay between batches
            if batch_start + batch_size < len(wallets):
                await asyncio.sleep(self.rate_limit_delay)
        
        elapsed_time = time.time() - start_time
        logger.info(
            f"Completed search for {len(results)} wallets in {elapsed_time:.2f}s "
            f"({elapsed_time/len(results):.2f}s per wallet)"
        )
        
        return results

