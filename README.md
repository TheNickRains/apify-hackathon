# Wallet Doxxer

Scrape Twitter/X to find wallet address owners. Get Twitter handles and confidence scores for any cryptocurrency wallet by searching public posts. Export data as JSON, CSV, or Excel.

> **Built for the [Apify $1M Challenge Hackathon](https://apify.notion.site/apify-1m-challenge-hackathon)**

## What does Wallet Doxxer do?

Wallet Doxxer searches Twitter/X for posts containing cryptocurrency wallet addresses using xAI's GROK with the `x_search` tool. For each wallet address, it:

1. **Searches Twitter/X** for any posts containing the wallet address
2. **Analyzes ownership context** to identify who posted it and why
3. **Assigns confidence scores** (High, Medium, Low, None) based on posting context
4. **Returns the Twitter handle** of the likely wallet owner

This Actor supports:

- **Ethereum addresses** (0x...)
- **Solana addresses** (base58)
- **Bitcoin addresses** (1.../3.../bc1...)
- **Other alphanumeric addresses** (20-100 chars)

## Why find wallet owners on Twitter?

Traditional X API access with `search_all` costs ~$5k/month. This Actor leverages xAI's GROK API with the `x_search` tool to search X at a fraction of the cost.

So what can you do with this data? Here are some ideas:

- **Enrich airdrop lists** with Twitter handles for social verification
- **Build allowlists** by connecting wallet addresses to Twitter identities
- **Research whale wallets** to discover who's behind large holdings
- **Verify DAO members** by linking wallet addresses to social profiles
- **Lead generation** for Web3 projects targeting active crypto users
- **Market research** on wallet holder demographics and social presence

## How to use Wallet Doxxer

1. **Provide wallet addresses** via paste, JSON array, or file URL
2. **Click Start** - no API keys needed, we fund the searches
3. **Export results** as CSV, JSON, or Excel from the dataset

### Input options

| Method | Best for |
|--------|----------|
| **Paste text** | Quick searches, copy from spreadsheet |
| **JSON array** | Programmatic API calls |
| **File URL** | Large datasets (10k+ wallets) |

### Example input

**Paste wallets (one per line):**
```
0x742d35Cc6634C0532925a3b844Bc9e7595f2bD12
0x8ba1f109551bD432803012645Ac136ddd64DBA72
5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM
```

**Or CSV format:**
```
wallet_address
0x742d35Cc6634C0532925a3b844Bc9e7595f2bD12
0x8ba1f109551bD432803012645Ac136ddd64DBA72
```

## How many wallets can you search?

This Actor is built for **production scale**:

| Dataset Size | Recommended Settings | Time |
|--------------|---------------------|------|
| 1-100 wallets | Default settings | ~3 minutes |
| 100-1,000 wallets | Default settings | ~30 minutes |
| 1,000-10,000 wallets | `batchLimit: 5000` | ~2.5 hours per batch |
| 10,000-50,000 wallets | `batchLimit: 5000` | Multiple runs, auto-resume |

For large datasets, the Actor automatically saves progress and can resume from where it left off if interrupted.

## Output

Results are saved to the Apify dataset and can be exported as JSON, CSV, XML, or Excel.

### Sample output

```json
{
  "wallet": "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD12",
  "postExists": true,
  "twitterHandle": "@cryptowhale",
  "confidence": "High"
}
```

### Output fields

| Field | Type | Description |
|-------|------|-------------|
| `wallet` | String | The wallet address searched |
| `postExists` | Boolean | Whether any Twitter post was found |
| `twitterHandle` | String | Twitter username of likely owner (e.g., @username) |
| `confidence` | String | Confidence level: High, Medium, Low, or None |

### Confidence levels explained

| Level | Meaning | Examples |
|-------|---------|----------|
| **High** | Clear ownership signal | User posted wallet in airdrop thread, bio, or "send tips here" |
| **Medium** | Strong indication | Wallet shared in trading context, donation request |
| **Low** | Weak signal | Wallet just mentioned or quoted with minimal context |
| **None** | No ownership found | Post exists but no clear owner identified |

## Production features

### Checkpoint & Resume

- Progress saved automatically every 10 wallets to Apify Key-Value Store
- If the Actor times out or errors, just run again - picks up where it left off
- Checkpoint validates against input hash to prevent data mismatch

### Batch processing

For large datasets, set `batchLimit` to process in chunks:

```json
{
  "inputFile": "https://example.com/33k-wallets.csv",
  "batchLimit": 5000
}
```

Run the Actor multiple times - each run processes 5000 wallets and saves progress.

## FAQ

### How accurate is the wallet owner identification?

The Actor uses a two-agent workflow: first checking if any post exists, then analyzing context for ownership signals. High confidence results are typically 85%+ accurate. Medium confidence requires manual verification.

### What if a wallet has no Twitter posts?

The Actor returns `postExists: false` and `confidence: None`. This means no public Twitter posts containing that wallet address were found.

### Can I use this for private/sensitive data?

This Actor only searches **public** Twitter posts. It does not access private accounts, DMs, or any non-public data.

### How do I process very large datasets (50k+ wallets)?

Use `batchLimit: 5000` and run the Actor multiple times. Each run resumes from the checkpoint. For 50k wallets, expect ~10 runs over several days.

### Can I integrate this with other tools?

Yes! Use Apify integrations with Make, Zapier, Google Sheets, or call the API directly. See the API tab for code examples.

## Integrations

Wallet Doxxer can be connected with almost any cloud service or web app thanks to integrations on the Apify platform:

- **Make** (formerly Integromat)
- **Zapier**
- **Google Sheets**
- **Slack**
- **Airbyte**
- **Webhooks**

Or use the Apify API for programmatic access. See the API tab for examples in Python, JavaScript, and cURL.

## Related tools

If you're working with crypto data, you might also find these useful:

- Blockchain explorers for transaction data
- Token holder scrapers
- NFT metadata extractors

## Your feedback

We're always working on improving performance. If you've got technical feedback or found a bug, please create an issue on the Actor's Issues tab in Apify Console.

## License

MIT
