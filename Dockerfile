# GROK Wallet Doxxer - Apify Actor
# Uses Python 3.11 with Apify SDK

FROM apify/actor-python:3.11

# Copy requirements first for better caching
COPY requirements.txt ./

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . ./

# Set working directory to src for imports
WORKDIR /usr/src/app/src

# Run the actor
CMD ["python", "main.py"]

