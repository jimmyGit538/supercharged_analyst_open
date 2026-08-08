FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Vendor dbt_utils at build time — the Cloud Run Jobs have no network egress
# guarantee and the _schema.yml tests reference dbt_utils macros, which dbt
# resolves at parse time.
RUN dbt deps --project-dir /app

# Default: build every layer. dbt resolves cross-layer order from ref(), so no
# explicit --select sequence is needed. There are no seeds, so no `dbt seed`.
#
# The Cloud Run Jobs do not use this CMD: infra/terraform/locals.tf passes
# args = ["sh", "-c", "dbt run ... --select <layer>"], which overrides it to run
# one layer per job.
CMD ["sh", "-c", "dbt run --profiles-dir /app --project-dir /app --target cloudrun"]
