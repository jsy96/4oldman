FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY careapp careapp
COPY web web
COPY server.py config.json ./
EXPOSE 8000
CMD ["python", "server.py"]
