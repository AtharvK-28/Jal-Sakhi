FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python backend dependencies
COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy application source code and pre-built frontend distribution
COPY backend/ ./backend/
COPY frontend/dist/ ./frontend/dist/
COPY sim_output/ ./sim_output/
COPY docs/ ./docs/
COPY run.py ./

EXPOSE 8000

CMD ["python", "run.py"]
