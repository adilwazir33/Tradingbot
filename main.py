import os, requests, threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CommandHandler, ContextTypes

BOT_TOKEN = os.environ.get("BOT_TOKEN")
print(f"TOKEN CHECK: {bool(BOT_TOKEN)}", flush=True)

flask_app = Flask(__name__)
@flask_app.route('/')
def home():
    return "BOT LIVE - OK" if BOT_TOKEN else "TOKEN MISSING"

def run_flask():
    flask_app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

SYMBOLS = {"BTC":"BTCUSDT","GOLD":"PAXGUSDT","EUR":"EURUSDT"}
TF = ["15m","1h","4h"]

def get_price(symbol, interval):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=100"
        data = requests.get(url, timeout=10).json()
        return [float(c[4]) for c in data]
    except:
        return None

def ema(data, p):
    k = 2/(p+1)
    e = data[0]
    for x in data[1:]:
        e = x*k + e*(1-k)
    return e

def make_msg():
    txt = "HACKER TERMINAL v9.0\n\n"
    for name, sym in SYMBOLS.items():
        txt += f"-- {name} --\n"
        for tf in TF:
            closes = get_price(sym, tf)
            if not closes:
                continue
            price = closes[-1]
            e21 = ema(closes, 21)
            e50 = ema(closes, 50)
            trend = "BULLISH" if e21 > e50 else "BEARISH"
            score = 80 if price > e21 else 20
            sig = "BUY NOW" if score>=80 else "SELL NOW" if score<=20 else "WAIT"
            txt += f"{tf} | {trend} | Score:{score} | {sig} | ${price:.2f}\n"
        txt += "\n"
    return txt

async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(make_msg())

def main():
    # Flask ko thread me chalao
    threading.Thread(target=run_flask, daemon=True).start()

    if not BOT_TOKEN:
        print("TOKEN MISSING!", flush=True)
        return

    print("Deleting webhook...", flush=True)
    requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=True", timeout=10)

    print("Starting polling in main thread...", flush=True)
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", reply))
    app.add_handler(CommandHandler("signal", reply))
    app.add_handler(MessageHandler(filters.TEXT, reply))
    print("POLLING LIVE - READY!", flush=True)
    # FIX: stop_signals=None taake thread wala error na aaye
    app.run_polling(drop_pending_updates=True, stop_signals=None)

if __name__ == "__main__":
    main()
