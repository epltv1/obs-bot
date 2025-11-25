#!/bin/bash
cd /root/obs-bot
git pull
source venv/bin/activate
pip install -r requirements.txt --quiet
pkill -f obs.py
nohup ./run.sh > bot.log 2>&1 &
echo "Bot updated & restarted!"
