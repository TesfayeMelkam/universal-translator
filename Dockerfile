FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd --create-home app && mkdir -p /app/data && chown -R app /app
USER app
EXPOSE 8000
# --proxy-headers: behind Caddy, rate limits and logs should see each visitor's real address
CMD ["python", "-m", "uvicorn", "ai_services.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
