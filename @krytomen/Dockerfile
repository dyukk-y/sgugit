FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DB_PATH=/app/data/sgugit.sqlite3 \
    PORT=8080

WORKDIR /app

# All project dependencies have Linux/Python 3.12 wheels.
# Do NOT install aiogram/aiohttp from source and do NOT require gcc.
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --only-binary=:all: -r requirements.txt \
    && python -c 'import openpyxl, requests, telegram, fastapi, uvicorn, dotenv, llama_cpp; print("production dependencies OK")' 

COPY src ./src
COPY .env.example ./
COPY README.md ./

RUN mkdir -p /app/data /app/data/reports

EXPOSE 8080

CMD ["python", "src/sgugit_bot/main.py"]
