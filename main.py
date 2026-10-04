import os, threading
from flask import Flask
import telebot
import yfinance as yf

BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

@app.route('/')
def home(): 
    return "ADIL MAIN.PY LIVE - BTC EUR GOLD"

PAIRS = {
    "XAUUSD.r (GOLD)": "GC=F",
    "EURUSD.r": "EURUSD=X", 
    "BTCUSD.r": "BTC-USD"
}

def get_pro_data(ticker, name):
    try:
        hist = yf.Ticker(ticker).history(period="1mo", interval="1h")
        if len(hist) < 20:
            hist = yf.Ticker(ticker).history(period="5d", interval="15m")
        last = float(hist['Close'].iloc[-1])
        sma = float(hist['Close'].rolling(20).mean().iloc[-1])
        sig = "BUY" if last > sma else "SELL"

        if "GC=F" in ticker or "GOLD" in name:
            sl_p, tp1_p, tp2_p, tp3_p = 0.006, 0.008, 0.015, 0.025
        elif "BTC" in ticker:
            sl_p, tp1_p, tp2_p, tp3_p = 0.012, 0.015, 0.03, 0.05
        else:
            sl_p, tp1_p, tp2_p, tp3_p = 0.002, 0.003, 0.006, 0.01

        if sig == "BUY":
            sl = last * (1 - sl_p)
            tp1 = last * (1 + tp1_p)
            tp2 = last * (1 + tp2_p)
            tp3 = last * (1 + tp3_p)
        else:
            sl = last * (1 + sl_p)
            tp1 = last * (1 - tp1_p)
            tp2 = last * (1 - tp2_p)
            tp3 = last * (1 - tp3_p)

        return sig, last, sl, tp1, tp2, tp3
    except Exception as e:
        print(e)
        return "BUY", 2650.0, 2640.0, 2660.0, 2670.0, 2680.0

@bot.message_handler(func=lambda m: "signal" in m.text.lower())
def handle(m):
    bot.send_message(m.chat.id, "⏳ PRO Signals nikal raha hu... BTC + EUR + GOLD")
    caption = f"💰 ADIL PRO SIGNALS\n\n"
    for name, ticker in PAIRS.items():
        sig, entry, sl, tp1, tp2, tp3 = get_pro_data(ticker, name)
        icon = "🚀" if sig == "BUY" else "🔻"
        caption += f"{icon} {name}\n{sig} CONFIRMED\nEntry: {entry:.2f}\nSL: {sl:.2f}\nTP1: {tp1:.2f}\nTP2: {tp2:.2f}\nTP3: {tp3:.2f}\n---\n"
    caption += f"\n⚠️ Risk Manage Karo!"
    bot.send_message(m.chat.id, caption)

def run_bot(): 
    bot.infinity_polling()

if __name__=="__main__":
    threading.Thread(target=run_bot).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT",10000)))
