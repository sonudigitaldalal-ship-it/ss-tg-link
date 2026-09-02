# Ek hi container mein Python (Telegram bot) + Node.js (WhatsApp bridge) chalane ke liye

FROM node:20-bookworm-slim

# ── System deps: Python + Chromium (dono bots ko chahiye) + git (npm ke liye) ──
RUN apt-get update && apt-get install -y \
    python3 python3-pip python3-venv \
    chromium \
    git \
    fonts-liberation libnss3 libnspr4 libatk-bridge2.0-0 libatk1.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libasound2 libpango-1.0-0 libcairo2 libx11-6 \
    libxext6 libxi6 libxtst6 libxss1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── WhatsApp bridge (Node.js) deps ──
COPY wa-bridge/package*.json ./wa-bridge/
RUN cd wa-bridge && npm install

# ── Telegram bot (Python) deps ──
COPY telegram-bot/requirements.txt ./telegram-bot/
RUN pip3 install --break-system-packages -r telegram-bot/requirements.txt
RUN pip3 install --break-system-packages playwright && \
    playwright install chromium --with-deps

# ── Copy rest of the code ──
COPY . .

RUN chmod +x start.sh
CMD ["./start.sh"]
