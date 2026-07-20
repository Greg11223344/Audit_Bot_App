FROM python:3.11-slim

WORKDIR /app

# Install dependencies first so this layer is cached across code-only changes.
COPY server/requirements.txt server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt

# app/main.py expects field-app/ and admin-app/ as siblings of server/ (BASE_DIR.parent) --
# preserve that layout inside the image.
COPY server/ server/
COPY field-app/ field-app/
COPY admin-app/ admin-app/

WORKDIR /app/server

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# $PORT is injected by Render/Railway/most PaaS platforms; default to 8000 for local `docker run`.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
