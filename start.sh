#!/bin/bash
# Dono processes ek saath start karta hai — agar koi ek crash ho jaye,
# poora container restart ho jayega (Railway apne aap restart karega).

set -e

echo "🚀 Starting WhatsApp bridge..."
cd /app/wa-bridge && node index.js &
WA_PID=$!

echo "🚀 Starting Telegram bot..."
cd /app/telegram-bot && python3 telegram_screenshot.py &
TG_PID=$!

# Jo bhi pehle exit ho, uska exit code lo aur dono ko band kar do
wait -n $WA_PID $TG_PID
EXIT_CODE=$?

echo "⚠️ Ek process band ho gaya (exit code $EXIT_CODE), dono band kar rahe hain..."
kill $WA_PID $TG_PID 2>/dev/null || true
exit $EXIT_CODE
