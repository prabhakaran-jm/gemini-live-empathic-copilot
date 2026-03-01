# Empathic Co-Pilot backend – Cloud Run
FROM python:3.12-slim

WORKDIR /app

# Unbuffered output so Cloud Run logs show crashes immediately
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application
COPY app/ ./app/
COPY run.py .

# Verify app imports (surfaces import errors at build time)
RUN python -c "from app.main import app; print('app OK')"

EXPOSE 8080

# Cloud Run sets PORT at runtime; bind to 0.0.0.0
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
