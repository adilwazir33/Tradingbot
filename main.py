import ccxt
import telebot
import os
from flask import Flask
import threading

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    BOT_TOKEN = "8747062832:AAHSM-scnf25COvXaADnFgOLWJ7ZV9l-tjE"

app = Flask(__name__)
# OKX - Dubai aur USA dono me chalta hai, Bybit block hai
exchange = ccxt.okx({'enableRateLimit': True})
bot = telebot.TeleBot(BOT_TOKEN)

def ema(prices, period):
    k = 2 / (period + 1)
    ema_val = prices[0]
    for p in prices[1:]:
        ema_val = p * k + ema_val * (1 - k)
    return ema_val

def get_signal():
    try:
        c15 = [x[4] for x in exchange.fetch_ohlcv('BTC/USDT', '15m', limit=60)]
        c1h = [x[4] for x in exchange.fetch_ohlcv('BTC/USDT', '1h', limit=60)]
        c4h = [x[4] for x in exchange.fetch_ohlcv('BTC/USDT', '4h', limit=60)]

        price = c15[-1]
        e15 = ema(c15, 50)
        e1h = ema(c1h, 50)
        e4h = ema(c4h, 50)

        if price > e15 and price > e1h and price > e4h:
            return f"✅ LONG SIGNAL - BTC\n\nPrice: {price}\n15M EMA50: {e15:.2f}\n1H EMA50: {e1h:.2f}\n4H EMA50: {e4h:.2f}\n\nSL: {price*0.995:.2f}\nTP: {price*1.015:.2f}\n\nTrend: Behtareen Uptrend Adil Bhai!"
        elif price < e15 and price < e1h and price < e4h:
            return f"🔴 SHORT SIGNAL - BTC\n\nPrice: {price}\n15M EMA50: {e15:.2f}\n1H EMA50: {e1h:.2f}\n4H EMA50: {e4h:.2f}\n\nSL: {price*1.005:.2f}\nTP: {price*0.985:.2f}\n\nTrend: Downtrend!"
        else:
            return f"⏳ NO TRADE\n\nPrice: {price}\n15M: {e15:.2f}\n1H: {e1h:.2f}\n4H: {e4h:.2f}\n\nMarket Sideways hai Adil Bhai, wait karo."
    except Exception as e:
        return f"Error: {e}"

@bot.message_handler(commands=['start'])
def start(m):
    bot.reply_to(m, "Adil Bhai Bot Live Hai! /signal likho")

@bot.message_handler(commands=['signal'])
def sig(m):
    bot.reply_to(m, "Signal nikal raha hu Adil Bhai... ⏳")
    bot.reply_to(m, get_signal())

@app.route('/')
def home():
    return "Adil Bhai Behtareen Bot Live 24/7 Dubai"

def run_bot():
    bot.infinity_polling()

threading.Thread(target=run_bot).start()
app.run(host="0.0.0.0", port=10000)
