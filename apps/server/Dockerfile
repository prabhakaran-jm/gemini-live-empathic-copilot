# Empathic Co-Pilot backend – Cloud Run
FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application
COPY app/ ./app/
COPY run.py .

# Cloud Run sets PORT at runtime; bind to 0.0.0.0
ENV PORT=8080
EXPOSE 8080

# Single process: uvicorn (no reload in production)
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
