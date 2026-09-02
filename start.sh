#!/bin/bash
# Dono processes independently apni-apni restart-loop mein chalte hain.
# Agar WA bridge crash ho, sirf wo restart hoga — Telegram bot chalta rahega,
# aur vice versa. Poora container tabhi restart hoga jab dono ek saath fail ho
# jayein (Railway health-check timeout, waghera).

echo "🚀 Starting WhatsApp bridge (auto-restart loop)..."
(
  cd /app/wa-bridge
  while true; do
    node index.js
    echo "⚠️ WhatsApp bridge crash ho gaya, 5 sec baad restart..."
    sleep 5
  done
) &

echo "🚀 Starting Telegram bot (auto-restart loop)..."
(
  cd /app/telegram-bot
  while true; do
    python3 telegram_screenshot.py
    echo "⚠️ Telegram bot crash ho gaya, 5 sec baad restart..."
    sleep 5
  done
) &

# Container ko zinda rakho jab tak dono background loops chal rahe hain
wait
