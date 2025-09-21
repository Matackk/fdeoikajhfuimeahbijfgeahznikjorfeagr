FROM python:3.12-slim
WORKDIR /app

# Dépendances (pas besoin de requirements.txt)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir "python-telegram-bot>=21,<22"

# Copie le code
COPY . .

ENV PYTHONUNBUFFERED=1
# Par défaut: polling (PUBLIC_URL non défini). Si tu mets PUBLIC_URL plus tard, le bot passera en webhook.
CMD ["python", "bot.py"]
