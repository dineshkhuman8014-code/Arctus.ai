FROM python:3.11-slim

RUN apt-get update && apt-get install -y curl gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs

RUN npm install -g omniroute

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir -e ".[server]"

EXPOSE 7860 20128

CMD omniroute & python -m server.app
