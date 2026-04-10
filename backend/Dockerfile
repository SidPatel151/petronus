FROM python:3.11-slim

WORKDIR /app

# System deps for shapely/pyproj
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgeos-dev libproj-dev gcc g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-prod.txt .
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
