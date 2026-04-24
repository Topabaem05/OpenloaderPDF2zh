FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-17-jre-headless \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml requirements.txt README.md app.py ./
COPY .env.example ./
COPY assets ./assets
COPY src ./src

RUN pip install --upgrade pip \
    && pip install -e .

EXPOSE 7860

CMD ["python", "app.py"]
