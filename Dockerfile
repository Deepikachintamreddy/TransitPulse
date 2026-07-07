FROM python:3.10-slim

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy dependencies and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source files
COPY . .

# Pre-generate the analytics dataset during build to ensure instant container startup
RUN python generate_pings.py --scale small && \
    python pipeline.py --input data/pings --output data/output

# Expose FastAPI port for Hugging Face compatibility
EXPOSE 7860

# Command to run backend server
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "7860"]
