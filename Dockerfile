FROM python:3.12-slim
WORKDIR /app
COPY requirements-fly.txt .
RUN pip install --no-cache-dir -r requirements-fly.txt
COPY crypto_bot.py run_loop.py ./
ENV PYTHONUNBUFFERED=1
CMD ["python", "run_loop.py"]
