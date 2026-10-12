FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 SAWT_RUNTIME_DIR=/tmp/sawt
WORKDIR /app
COPY requirements*.txt ./
RUN pip install --no-cache-dir -r requirements-cloud.txt
COPY sawt/ ./sawt/
COPY data/ ./data/
COPY voice_worker.py ./
RUN useradd --create-home appuser
USER appuser
CMD ["python", "voice_worker.py", "start"]
