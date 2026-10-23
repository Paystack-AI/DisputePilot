FROM python:3.12-slim

WORKDIR /ai

COPY requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN addgroup --system --gid 10001 app \
    && adduser --system --uid 10001 --ingroup app app \
    && chown -R app:app /ai

USER app

CMD ["python", "-m", "src.worker"]
