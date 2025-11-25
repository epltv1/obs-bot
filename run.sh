#!/bin/bash
cd /root/obs-bot

# Kill old
pkill -f obs.py

# Wait
sleep 2

# Start with FULL LOGS
echo "[$(date)] Starting bot..." >> data/bot.log
nohup python obs.py >> data/bot.log 2>&1 &

echo "Bot started! Check data/bot.log for logs."
