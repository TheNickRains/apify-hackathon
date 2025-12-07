# Wallet Doxxer - Apify Actor
FROM apify/actor-python:3.13

# Copy requirements first for caching
COPY --chown=myuser:myuser requirements.txt ./

# Install dependencies
RUN pip install -r requirements.txt

# Copy source code
COPY --chown=myuser:myuser . ./

# Verify Python code compiles
RUN python3 -m compileall -q src/

# Run as module
CMD ["python3", "-m", "src"]
