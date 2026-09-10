FROM python:3.12-slim

WORKDIR /code

# requirements.txt lleva versiones exactas y hashes, compilado desde
# requirements.in. --require-hashes obliga a que cada paquete descargado
# coincida con el hash anotado: dos construcciones del mismo commit instalan
# exactamente lo mismo, y un paquete manipulado en el camino no entra.
COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt

COPY . .

EXPOSE 8000

# El contenedor solo sirve la API. Las migraciones corren en el servicio
# `migrate` del compose, con el dueño de la base: si se aplicaran aquí, la API
# tendría que conectarse con permisos de DDL para arrancar y los conservaría
# mientras atiende peticiones.
#
# Límites de uvicorn: cierra conexiones ociosas y acota la concurrencia para
# que una avalancha de conexiones no agote los recursos del proceso.
# --proxy-headers con --forwarded-allow-ips acotado a la red Docker del proxy
# (Caddy, 172.28.0.0/16): solo se confía en el X-Forwarded-For que pone Caddy,
# así el rate limiting por IP ve la IP real del cliente. Se acota a la subred
# en vez de "*" para que nadie pueda falsear la IP si algún día se vuelve a
# exponer el puerto directamente.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--limit-concurrency", "100", "--timeout-keep-alive", "5", "--proxy-headers", "--forwarded-allow-ips=172.28.0.0/16"]
