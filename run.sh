#!/bin/bash
cd /root/obs-bot

# Kill old
pkill -f obs.py

# Start with log
nohup python obs.py > data/bot.log 2>&1 &
echo "Bot started!"
