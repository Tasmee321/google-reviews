FROM python:3.11-slim

# Chrome dependencies
RUN apt-get update && apt-get install -y \
    wget curl gnupg unzip \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 \
    libpango-1.0-0 libcairo2 libasound2 \
    libx11-6 libx11-xcb1 libxcb1 libxext6 \
    libxss1 libxtst6 fonts-liberation \
    xvfb dbus-x11 \
    --no-install-recommends && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install patchright browsers
RUN python -m patchright install chromium
RUN python -m patchright install-deps chromium

COPY . .

# Xvfb virtual display — patchright needs display even in "headless" mode
ENV DISPLAY=:99
ENV HEADLESS=true
ENV PYTHONUNBUFFERED=1

CMD Xvfb :99 -screen 0 1366x768x24 -ac +extension GLX +render -noreset & \
    sleep 2 && \
    python app.py
