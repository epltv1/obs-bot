#!/bin/bash
cd /root/obs-bot

# Kill old bot
pkill -f obs.py

# Wait
sleep 2

# Start with FULL LOGS using python3
echo "[$(date)] Starting bot with python3..." >> data/bot.log
nohup python3 obs.py >> data/bot.log 2>&1 &

echo "Bot started! Check: tail -f data/bot.log"
