FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -r requirements.txt && mkdir -p /app/data
ENV DB_PATH=/app/data/sgugit.sqlite3
EXPOSE 8080
CMD ["python", "src/sgugit_bot/main.py"]
