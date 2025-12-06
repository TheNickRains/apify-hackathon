"""
Input parser for multiple formats: CSV, JSON, and plain text.
Handles both direct input and file URLs.
"""

import csv
import json
import io
import re
import httpx
from typing import Optional


async def fetch_file_content(url: str) -> str:
    """Fetch file content from a URL."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


def parse_csv(content: str, wallet_column: str = "wallet_address") -> list[str]:
    """Parse CSV content and extract wallet addresses from specified column."""
    wallets = []
    reader = csv.DictReader(io.StringIO(content))
    
    # Find the wallet column (case-insensitive)
    fieldnames = reader.fieldnames or []
    actual_column = None
    
    for field in fieldnames:
        if field.lower() == wallet_column.lower():
            actual_column = field
            break
        # Also check for common variations
        if "wallet" in field.lower() and "address" in field.lower():
            actual_column = field
            break
        if field.lower() in ["wallet", "address", "wallet_address", "walletaddress"]:
            actual_column = field
            break
    
    if not actual_column:
        # If no column found, try first column
        if fieldnames:
            actual_column = fieldnames[0]
        else:
            return wallets
    
    for row in reader:
        wallet = row.get(actual_column, "").strip()
        if wallet and is_valid_wallet(wallet):
            wallets.append(wallet)
    
    return wallets


def parse_json(content: str) -> list[str]:
    """Parse JSON content - handles array of strings or array of objects."""
    data = json.loads(content)
    wallets = []
    
    if isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                # Array of wallet strings
                if is_valid_wallet(item.strip()):
                    wallets.append(item.strip())
            elif isinstance(item, dict):
                # Array of objects - look for wallet field
                for key in ["wallet", "wallet_address", "walletAddress", "address"]:
                    if key in item:
                        wallet = str(item[key]).strip()
                        if is_valid_wallet(wallet):
                            wallets.append(wallet)
                        break
    elif isinstance(data, dict):
        # Single object with wallets array
        for key in ["wallets", "wallet_addresses", "walletAddresses", "addresses", "data"]:
            if key in data and isinstance(data[key], list):
                return parse_json(json.dumps(data[key]))
    
    return wallets


def parse_text(content: str) -> list[str]:
    """Parse plain text - one wallet per line."""
    wallets = []
    for line in content.strip().split("\n"):
        wallet = line.strip()
        if wallet and is_valid_wallet(wallet):
            wallets.append(wallet)
    return wallets


def is_valid_wallet(address: str) -> bool:
    """Basic validation for wallet address formats."""
    if not address or len(address) < 10:
        return False
    
    # Ethereum-style addresses (0x...)
    if re.match(r"^0x[a-fA-F0-9]{40}$", address):
        return True
    
    # Solana addresses (base58, 32-44 chars)
    if re.match(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$", address):
        return True
    
    # Bitcoin addresses (various formats)
    if re.match(r"^(1|3|bc1)[a-zA-HJ-NP-Z0-9]{25,62}$", address):
        return True
    
    # Generic alphanumeric (fallback for other chains)
    if re.match(r"^[a-zA-Z0-9]{20,100}$", address):
        return True
    
    return False


def detect_format(content: str) -> str:
    """Detect the format of the input content."""
    content = content.strip()
    
    # Check for JSON
    if content.startswith("[") or content.startswith("{"):
        try:
            json.loads(content)
            return "json"
        except json.JSONDecodeError:
            pass
    
    # Check for CSV (has commas and newlines, or header row)
    lines = content.split("\n")
    if len(lines) > 1:
        first_line = lines[0]
        if "," in first_line:
            # Check if it looks like a CSV header
            if any(word in first_line.lower() for word in ["wallet", "address", "id"]):
                return "csv"
            # Check if second line also has commas
            if len(lines) > 1 and "," in lines[1]:
                return "csv"
    
    # Default to text (one per line)
    return "text"


async def parse_input(
    wallet_addresses: Optional[list] = None,
    wallet_text: Optional[str] = None,
    input_file: Optional[str] = None,
    wallet_column: str = "wallet_address"
) -> list[str]:
    """
    Parse wallet addresses from various input sources.
    
    Args:
        wallet_addresses: Direct list of wallet addresses (JSON array)
        wallet_text: Raw text/CSV content pasted by user
        input_file: URL to a file containing wallet addresses
        wallet_column: Column name for CSV files
        
    Returns:
        List of wallet addresses
    """
    wallets = []
    
    # First, handle direct wallet addresses input (JSON array)
    if wallet_addresses:
        if isinstance(wallet_addresses, list):
            for addr in wallet_addresses:
                if isinstance(addr, str) and is_valid_wallet(addr.strip()):
                    wallets.append(addr.strip())
                elif isinstance(addr, dict):
                    # Handle objects with wallet field
                    for key in ["wallet", "wallet_address", "walletAddress", "address"]:
                        if key in addr:
                            wallet = str(addr[key]).strip()
                            if is_valid_wallet(wallet):
                                wallets.append(wallet)
                            break
    
    # Handle pasted text/CSV content
    if wallet_text and wallet_text.strip():
        text_format = detect_format(wallet_text)
        
        if text_format == "csv":
            text_wallets = parse_csv(wallet_text, wallet_column)
        elif text_format == "json":
            text_wallets = parse_json(wallet_text)
        else:
            text_wallets = parse_text(wallet_text)
        
        wallets.extend(text_wallets)
    
    # Handle file URL input
    if input_file:
        try:
            content = await fetch_file_content(input_file)
            file_format = detect_format(content)
            
            if file_format == "csv":
                file_wallets = parse_csv(content, wallet_column)
            elif file_format == "json":
                file_wallets = parse_json(content)
            else:
                file_wallets = parse_text(content)
            
            wallets.extend(file_wallets)
        except Exception as e:
            raise ValueError(f"Failed to fetch or parse input file: {e}")
    
    # Remove duplicates while preserving order
    seen = set()
    unique_wallets = []
    for wallet in wallets:
        if wallet not in seen:
            seen.add(wallet)
            unique_wallets.append(wallet)
    
    return unique_wallets

