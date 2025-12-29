# Stage 1: Builder (install dependencies)
FROM python:3.12-slim-bookworm AS builder
WORKDIR /app

# Install system dependencies needed for Python packages (e.g., psycopg2)
RUN apt-get update && apt-get install -y postgresql-client build-essential && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

ENV PYTHONUNBUFFERED=1
COPY . /app

RUN pip install --no-cache-dir -r requirements.txt
RUN pip install gunicorn | tee pip-install.out

# Run collectstatic (configure in settings)
# RUN python manage.py collectstatic --noinput
EXPOSE 8000
# Use Gunicorn as the production WSGI server, not the Django dev server
CMD ["gunicorn", "--bind", ":8000", "--workers", "3", "your_project_name.wsgi:application"]
