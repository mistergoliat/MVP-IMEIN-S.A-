FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
COPY requirements.txt ./
# Speed up pip and avoid network flakiness during builds
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=180 \
    PIP_NO_CACHE_DIR=1 \
    PIP_RETRIES=10
RUN pip install -r requirements.txt \
    && pip install -e . --no-deps

COPY app ./app

ENV PYTHONPATH=/app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
