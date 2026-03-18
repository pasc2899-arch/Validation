FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    wget curl gnupg libnss3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libasound2 fonts-liberation \
    libappindicator3-1 libxss1 \
    --no-install-recommends && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium && playwright install-deps chromium

COPY runt_license_validator.py .
COPY simit_validator.py .
COPY runt_api.py .

EXPOSE 5050
CMD ["gunicorn", "--bind", "0.0.0.0:5050", "--timeout", "180", "--workers", "1", "runt_api:app"]
