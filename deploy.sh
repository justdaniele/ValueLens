#!/bin/bash

# ValueLens deployment script for Raspberry Pi (systemd service)
set -e

SERVICE_NAME="valuelens"
SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME.service"

echo "Installing systemd service for ValueLens..."

sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=ValueLens Telegram Bot
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$(pwd)
ExecStart=$(pwd)/venv/bin/python $(pwd)/bot.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl start "$SERVICE_NAME"

echo "✔ Service '$SERVICE_NAME' installed and started."
EOF
