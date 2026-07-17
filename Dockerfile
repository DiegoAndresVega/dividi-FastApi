FROM python:3.12-slim

WORKDIR /code

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Límites de uvicorn: cierra conexiones ociosas y acota la concurrencia para
# que una avalancha de conexiones no agote los recursos del proceso.
# Sin --proxy-headers a propósito: al no haber un reverse proxy de confianza
# delante, confiar en X-Forwarded-For dejaría falsear la IP y saltarse el
# rate limiting. Se añadirá cuando montemos HTTPS con proxy.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --limit-concurrency 100 --timeout-keep-alive 5"]
