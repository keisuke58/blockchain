@echo off
cd /d c:\Users\nishi\git\blockchain
python live_bot.py --budget 10 --symbol BTCEUR --strategy rsi >> logs\live_bot_run.log 2>&1
