FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN dbt deps --project-dir /app
# Seed static reference data then run all models
CMD ["sh", "-c", "dbt seed --profiles-dir /app --project-dir /app --target cloudrun && dbt run --profiles-dir /app --project-dir /app --target cloudrun"]
