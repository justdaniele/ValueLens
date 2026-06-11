#!/bin/bash
kill $(pgrep -f bot.py) 2>/dev/null && echo "bot.py stopped"
kill $(pgrep -f web_api) 2>/dev/null && echo "web_api.py stopped"
sudo tailscale funnel --https=443 off
echo "Tailscale funnel disabled"
