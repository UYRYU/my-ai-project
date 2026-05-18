FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY main.py .

RUN useradd -m -u 1000 bot && chown -R bot:bot /app
USER bot

EXPOSE 9100
CMD ["python", "-m", "src.ws_bot"]
