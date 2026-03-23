FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Run against the 'cloudrun' target (oauth, picks up the attached service account automatically)
CMD ["dbt", "run", "--profiles-dir", "/app", "--project-dir", "/app", "--target", "cloudrun"]
