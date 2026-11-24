# Image de l'API Supply Pulse
# Construction : docker compose build api   (après avoir entraîné les modèles : notebooks 02 et 03)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# libgomp1 : bibliothèque OpenMP requise par XGBoost
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dépendances d'abord : cette couche reste en cache tant que requirements-api.txt ne change pas.
COPY requirements-api.txt .
RUN pip install -r requirements-api.txt

COPY src/ src/
COPY models/ models/

# Pas d'exécution en root dans le conteneur
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=4)"

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
