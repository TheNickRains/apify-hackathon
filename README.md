# GROK Wallet Doxxer - Apify Actor

Search Twitter/X for wallet addresses using xAI's GROK with the `x_search` tool. Identifies wallet owners with confidence scores by analyzing posts containing wallet addresses.

> **Built for the [Apify $1M Challenge Hackathon](https://apify.notion.site/apify-1m-challenge-hackathon)**

## What It Does

This Actor takes a list of cryptocurrency wallet addresses and:

1. **Searches Twitter/X** for posts containing each wallet address
2. **Analyzes ownership** context to identify who posted it
3. **Assigns confidence scores** (High, Medium, Low, None) based on posting context
4. **Outputs results** to Apify Dataset (exportable as CSV/JSON)

## Why Use This?

Traditional X API access with `search_all` costs ~$5k/month. This Actor leverages xAI's GROK API with the `x_search` tool to programmatically search X at a fraction of the cost.

**Use cases:**
- Enrich wallet address lists with Twitter handles
- Identify wallet owners for airdrops, allowlists, or research
- Build wallet-to-social mappings for Web3 projects

## Input

Just provide your wallet addresses - no API keys needed!

| Field | Type | Description |
|-------|------|-------------|
| `walletAddresses` | array | JSON array of wallet addresses |
| `walletText` | string | Paste CSV or text directly (one wallet per line) |
| `inputFile` | string | URL to a hosted CSV/JSON/text file |

### Input Examples

**Paste CSV directly:**
```
wallet_address
0x742d35Cc6634C0532925a3b844Bc9e7595f2bD12
0x8ba1f109551bD432803012645Ac136ddd64DBA72
```

**Or one wallet per line:**
```
0x742d35Cc6634C0532925a3b844Bc9e7595f2bD12
0x8ba1f109551bD432803012645Ac136ddd64DBA72
```

**JSON array:**
```json
{
  "walletAddresses": [
    "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD12",
    "0x8ba1f109551bD432803012645Ac136ddd64DBA72"
  ]
}
```

**File URL:**
```json
{
  "inputFile": "https://example.com/wallets.csv"
}
```

CSV files should have a `wallet_address` column (or the first column will be used).

## Output

Results are saved to the default Apify Dataset. Each record contains:

```json
{
  "wallet": "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD12",
  "postExists": true,
  "twitterHandle": "@cryptouser123",
  "confidence": "High"
}
```

### Confidence Levels

| Level | Meaning |
|-------|---------|
| **High** | Clear ownership - user posted wallet in airdrop thread, bio, or explicit ownership statement |
| **Medium** | Strong indication - wallet shared for donations, trading, or user activity context |
| **Low** | Weak indication - wallet just mentioned or quoted with minimal context |
| **None** | No ownership indication found |

## Performance

- **~1.8 seconds per wallet** with parallel processing
- **Batch processing** for efficient rate limit management
- **Automatic retries** with exponential backoff on rate limits

## Supported Wallet Formats

- Ethereum (0x...)
- Solana (base58)
- Bitcoin (1.../3.../bc1...)
- Other alphanumeric addresses (20-100 chars)

## License

MIT
