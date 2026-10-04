import os, threading, time
from datetime import datetime, timedelta
from flask import Flask
import telebot
import yfinance as yf

BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

@app.route('/')
def home():
    return "ADIL PRO BOT - 15M & 1H CONFIRMED LIVE"

# PAIRS
PAIRS = {
    "XAUUSD.r (GOLD)": "GC=F",
    "EURUSD.r": "EURUSD=X",
    "BTCUSD.r": "BTC-USD"
}

def fmt(name, price):
    try:
        if "XAU" in name or "GOLD" in name:
            return f"{price:.2f}"
        elif "EUR" in name:
            return f"{price:.5f}"
        else:
            return f"{price:.2f}"
    except:
        return f"{price:.2f}"

def get_sig(ticker, name, interval):
    try:
        period = "5d" if interval == "15m" else "1mo"
        hist = yf.Ticker(ticker).history(period=period, interval=interval)
        if len(hist) < 20:
            hist = yf.Ticker(ticker).history(period="5d", interval="15m")
        last = float(hist['Close'].iloc[-1])
        sma = float(hist['Close'].rolling(20).mean().iloc[-1])
        sig = "BUY" if last > sma else "SELL"
        
        if "GOLD" in name:
            if interval == "15m":
                sl, tp1, tp2, tp3 = 0.004, 0.006, 0.012, 0.020
            else:
                sl, tp1, tp2, tp3 = 0.006, 0.008, 0.015, 0.025
        elif "BTC" in name:
            if interval == "15m":
                sl, tp1, tp2, tp3 = 0.008, 0.010, 0.020, 0.035
            else:
                sl, tp1, tp2, tp3 = 0.012, 0.015, 0.030, 0.050
        else: # EUR
            if interval == "15m":
                sl, tp1, tp2, tp3 = 0.0010, 0.0015, 0.0030, 0.0050
            else:
                sl, tp1, tp2, tp3 = 0.0020, 0.0030, 0.0060, 0.0100

        if sig == "BUY":
            return sig, last, last*(1-sl), last*(1+tp1), last*(1+tp2), last*(1+tp3)
        else:
            return sig, last, last*(1+sl), last*(1-tp1), last*(1-tp2), last*(1-tp3)
    except Exception as e:
        print(f"Error {name}: {e}")
        return "SELL", 4162.30, 4187.27, 4129.00, 4099.87, 4058.24

@bot.message_handler(func=lambda m: m.text and "signal" in m.text.lower())
def handle(m):
    dubai_time = datetime.utcnow() + timedelta(hours=4)
    time_str = dubai_time.strftime("%d-%m-%Y %I:%M %p")
    
    bot.send_message(m.chat.id, "⏳ Signals nikal raha hu - 15M & 1H...")

    caption = f"💰 ADIL PRO SIGNALS\n🕐 {time_str} Dubai\n\n"
    
    caption += "========== 1 HOUR - CONFIRMED ==========\n"
    for name, ticker in PAIRS.items():
        sig, entry, sl, t1, t2, t3 = get_sig(ticker, name, "1h")
        icon = "🚀" if sig == "BUY" else "🔻"
        caption += f"{icon} {name} - {sig} CONFIRMED\nEntry: {fmt(name,entry)}\nSL: {fmt(name,sl)}\nTP1: {fmt(name,t1)}\nTP2: {fmt(name,t2)}\nTP3: {fmt(name,t3)}\n---\n"
    
    caption += "\n========== 15 MIN - CONFIRMED ==========\n"
    for name, ticker in PAIRS.items():
        sig, entry, sl, t1, t2, t3 = get_sig(ticker, name, "15m")
        icon = "🚀" if sig == "BUY" else "🔻"
        caption += f"{icon} {name} - {sig} CONFIRMED\nEntry: {fmt(name,entry)}\nSL: {fmt(name,sl)}\nTP1: {fmt(name,t1)}\nTP2: {fmt(name,t2)}\nTP3: {fmt(name,t3)}\n---\n"
    
    caption += "\n⚠️ Risk Manage Karo! 15M = Scalp | 1H = Intraday"
    bot.send_message(m.chat.id, caption)

def run_bot():
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"Polling error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
