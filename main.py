import os
import requests
import time
from flask import Flask
from threading import Thread
import telebot

BOT_TOKEN = os.getenv("BOT_TOKEN")
SYMBOL = "BTCUSDT"
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

@app.route('/')
def home():
    return "1000% Working - Banking Pro Live"

def get_data(interval):
    try:
        url = f"https://data-api.binance.vision/api/v3/klines?symbol={SYMBOL}&interval={interval}&limit=100"
        r = requests.get(url, timeout=10).json()
        if not isinstance(r, list): return None
        closes = [float(x[4]) for x in r]
        return closes
    except:
        return None

def analyze(tf_code, tf_name):
    closes = get_data(tf_code)
    if not closes or len(closes) < 50: return None
    price = closes[-1]
    ema20 = sum(closes[-20:]) / 20
    ema50 = sum(closes[-50:])
