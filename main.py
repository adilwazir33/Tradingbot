import os, threading, time
from flask import Flask
import telebot
import yfinance as yf

# IMPORTANT: Token check
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN not set on Render!")
    BOT_TOKEN = "123:fake" # Flask ko alive rakhne ke liye

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

@app.route('/')
def home():
    return "ADIL BOT LIVE - 2026-10-04 - OK"

PAIRS = {
    "XAUUSD.r (GOLD)": "GC=F",
    "EURUSD.r": "EURUSD=X",
    "BTCUSD.r": "BTC-USD"
}

def get_pro_data(ticker, name):
    try:
        hist = yf.Ticker(ticker).history(period="1mo", interval="1h")
        if len(hist) < 5:
            return "BUY", 2650.0, 2630.0, 2670.0, 2690.0, 2710.0
        last = float(hist['Close'].iloc[-1])
        sma = float(hist['Close'].rolling(20).mean().iloc[-1])
        sig = "BUY" if last > sma else "SELL"
        
        if "GC=F" in ticker: sl_p,tp1,tp2,tp3 = 0.006,0.008,0.015,0.025
        elif "BTC" in ticker: sl_p,tp1,tp2,tp3 = 0.012,0.015,0.03,0.05
        else: sl_p,tp1,tp2,tp3 = 0.002,0.003,0.006,0.01
        
        if sig=="BUY":
            return sig,last,last*(1-sl_p),last*(1+tp1),last*(1+tp2),last*(1+tp3)
        else:
            return sig,last,last*(1+sl_p),last*(1-tp1),last*(1-tp2),last*(1-tp3)
    except:
        return "BUY", 2650.0, 2630.0, 2670.0, 2690.0, 2710.0

@bot.message_handler(func=lambda m: m.text and "signal" in m.text.lower())
def handle(m):
    try:
        caption = f"💰 ADIL PRO SIGNALS\n\n"
        for name, ticker in PAIRS.items():
            sig, entry, sl, t1, t2, t3 = get_pro_data(ticker, name)
            icon = "🚀" if sig=="BUY" else "🔻"
            caption += f"{icon} {name}\n{sig}\nEntry: {entry:.2f}\nSL: {sl:.2f}\nTP1: {t1:.2f}\nTP2: {t2:.2f}\nTP3: {t3:.2f}\n---\n"
        bot.send_message(m.chat.id, caption)
    except Exception as e:
        print(f"Send error {e}")

def run_bot():
    while True:
        try:
            print("Bot polling started...")
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"Bot crashed {e}, restart in 5s")
            time.sleep(5)

# Flask ko pehle start karo
if __name__=="__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
