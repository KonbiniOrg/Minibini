FROM python:3.12-slim-bookworm
WORKDIR /app

# Install system dependencies needed for Python packages (e.g., psycopg2)
RUN apt update 
RUN apt install -y mariadb-client build-essential pkg-config python3-dev default-libmysqlclient-dev build-essential
COPY requirements.txt .

# ENV PYTHONUNBUFFERED=1
COPY . /app
RUN mkdir /app/static

RUN pip install --no-cache-dir -r requirements.txt
RUN pip install gunicorn | tee pip-install.out

# Run collectstatic (configure in settings)
# RUN python manage.py collectstatic --noinput
EXPOSE 8000
# Use Gunicorn as the production WSGI server, not the Django dev server
# CMD ["gunicorn", "--bind", ":8000", "--workers", "3", "minibini.wsgi:application"]
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
