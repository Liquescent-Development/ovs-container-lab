FROM python:3.11-slim

WORKDIR /app

# Install the Docker Python package
RUN pip install --no-cache-dir docker

# Copy the application
COPY docker-metrics.py .

EXPOSE 8080

CMD ["python", "docker-metrics.py"]
