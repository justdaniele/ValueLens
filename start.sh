#!/bin/bash
cd ~/Desktop/valuelens
source venv/bin/activate

nohup python3 -u bot.py > valuelens_master.log 2>&1 &
echo "bot.py started (PID $!)"

cd website
nohup python web_api.py &> web_api.log &
echo "web_api.py started (PID $!)"

cd ..
sudo tailscale funnel --bg 5000
echo "Tailscale funnel active on port 5000"
