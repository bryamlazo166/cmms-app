# Imagen de la app CMMS para el VPS (espejo secundario).
# Render (primario) NO usa este Dockerfile: alli el build lo define el dashboard.
# Contexto de build: la raiz del repo (ver docker-compose.yml).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080
CMD ["gunicorn", "--workers", "2", "--threads", "4", "--timeout", "120", "--bind", "0.0.0.0:8080", "app:app"]
