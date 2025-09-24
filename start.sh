#!/bin/bash
while true; do
    echo "Starting bot..."
    python3 bot.py >> bot.log 2>&1
    echo "Bot crashed with exit code $?. Restarting in 5 seconds..."
    sleep 5
done
