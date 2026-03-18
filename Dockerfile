FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY runt_license_validator.py .
COPY simit_validator.py .
COPY runt_api.py .

EXPOSE 5050
CMD ["gunicorn", "--bind", "0.0.0.0:5050", "--timeout", "180", "--workers", "1", "runt_api:app"]
