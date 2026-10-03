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
    return "Live - Full Pro Banking Bot Running"

def get_binance_data(interval):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={SYMBOL}&interval={interval}&limit=100"
        r = requests.get(url, timeout=10).json()
        closes = [float(c[4]) for c in r]
        highs = [float(c[2]) for c in r]
        lows = [float(c[3]) for c in r]
        return closes, highs, lows
    except:
        return None, None, None

def analyze_tf(interval_name, interval_code):
    closes, highs, lows = get_binance_data(interval_code)
    if not closes:
        return None
    price = closes[-1]
    ema_fast = sum(closes[-20:]) / 20
    ema_slow = sum(closes[-50:]) / 50
    gains, losses = [], []
    for i in range(1, 15):
        diff = closes[-i] - closes[-i-1]
        if diff > 0:
            gains.append(diff)
        else:
            losses.append(abs(diff))
    avg_gain = sum(gains)/14 if gains else 0.01
    avg_loss = sum(losses)/14 if losses else 0.01
    rsi = 100 - (100 / (1 + avg_gain/avg_loss))
    if price > ema_fast > ema_slow and 50 < rsi < 75:
        sig = "LONG"
    elif price < ema_fast < ema_slow and 25 < rsi < 50:
        sig = "SHORT"
    else:
        sig = "NO TRADE"
    return {"price": price, "signal": sig, "rsi": round(rsi,2), "low": min(lows[-20:]), "high": max(highs[-20:]), "tf": interval_name}

def format_signal(tf_data):
    if not tf_data:
        return "Data Error"
    p = tf_data['price']
    sig = tf_data['signal']
    tf = tf_data['tf']
    if sig == "NO TRADE":
        return f"{tf} - BTC\nPrice: {p:.2f}\nRSI: {tf_data['rsi']}\nStatus: NO TRADE"
    if sig == "LONG":
        sl, tp1, tp2, tp3 = p*0.988, p*1.012, p*1.025, p*1.04
        return f"BUY/LONG {tf} - BTC\nEntry: {p:.2f}\nTP1: {tp1:.2f} TP2: {tp2:.2f} TP3: {tp3:.2f}\nSL: {sl:.2f}\nRSI: {tf_data['rsi']}"
    else:
        sl, tp1, tp2, tp3 = p*1.012, p*0.988, p*0.975, p*0.96
        return f"SELL/SHORT {tf} - BTC\nEntry: {p:.2f}\nTP1: {tp1:.2f} TP2: {tp2:.2f} TP3: {tp3:.2f}\nSL: {sl:.2f}\nRSI: {tf_data['rsi']}"

def full_pro_analysis():
    tf_15m = analyze_tf("15MIN","15m")
    tf_1h = analyze_tf("1HOUR","1h")
    tf_4h = analyze_tf("4HOUR","4h")
    if not tf_15m or not tf_1h or not tf_4h:
        return "Binance busy, try again"
    long_c = sum(1 for x in [tf_15m,tf_1h,tf_4h] if x['signal']=="LONG")
    short_c = sum(1 for x in [tf_15m,tf_1h,tf_4h] if x['signal']=="SHORT")
    final = "BUY CONFIRMED" if long_c>=2 else "SELL CONFIRMED" if short_c>=2 else "WAIT"
    msg = f"FULL BANKING PRO - BTC {tf_15m['price']:.2f}\n\n{format_signal(tf_15m)}\n---\n{format_signal(tf_1h)}\n---\n{format_signal(tf_4h)}\n\nFINAL: {final} ({long_c}L vs {short_c}S)"
    return msg

@bot.message_handler(commands=['start'])
def start_cmd(m):
    bot.send_message(m.chat.id, "BANKING PRO BOT\n/signal - Full\n/15m - 15min\n/1h - 1 Hour\n/4h - 4 Hour\n/price - Price")

@bot.message_handler(commands=['signal','analysis'])
def signal_cmd(m):
    bot.send_message(m.chat.id, full_pro_analysis())

@bot.message_handler(commands=['15m'])
def c1(m):
    bot.send_message(m.chat.id, format_signal(analyze_tf("15MIN","15m")))

@bot.message_handler(commands=['1h'])
def c2(m):
    bot.send_message(m.chat.id, format_signal(analyze_tf("1HOUR","1h")))

@bot.message_handler(commands=['4h'])
def c3(m):
    bot.send_message(m.chat.id, format_signal(analyze_tf("4HOUR","4h")))

@bot.message_handler(commands=['price'])
def c4(m):
    closes, _, _ = get_binance_data("1m")
    if closes:
        bot.send_message(m.chat.id, f"BTC Price: {closes[-1]:.2f}")

def run_bot():
    while True:
        try:
            bot.infinity_polling()
        except:
            time.sleep(5)

if __name__ == "__main__":
    Thread(target=run_bot, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
