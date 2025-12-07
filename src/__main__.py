"""Entry point for running the Actor as a Python module."""

import asyncio
from .main import main

if __name__ == '__main__':
    asyncio.run(main())

