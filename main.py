import os, requests, threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CommandHandler, ContextTypes

BOT_TOKEN = os.environ.get("BOT_TOKEN")
print(f"TOKEN CHECK: {bool(BOT_TOKEN)}", flush=True)

flask_app = Flask(__name__)
@flask_app.route('/')
def home(): return "PRO BOT LIVE"
def run_flask(): flask_app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

SYMBOLS = {"BTC":"BTCUSDT","GOLD":"PAXGUSDT","EUR":"EURUSDT"}
TF = ["15m","1h","4h"]

def get_klines(symbol, interval):
    for base in ["https://data-api.binance.vision", "https://api.binance.com"]:
        try:
            url = f"{base}/api/v3/klines?symbol={symbol}&interval={interval}&limit=100"
            data = requests.get(url, timeout=10).json()
            if isinstance(data, list) and len(data) > 60:
                return data
        except: continue
    return None

def ema(values, p):
    k = 2/(p+1)
    e = values[0]
    for x in values[1:]: e = x*k + e*(1-k)
    return e

def rsi(closes, period=14):
    gains, losses = 0, 0
    for i in range(1, period+1):
        diff = closes[-i] - closes[-i-1]
        if diff>0: gains+=diff
        else: losses+=abs(diff)
    if losses==0: return 70
    rs = gains/losses
    return 100 - (100/(1+rs))

def get_signal(symbol, interval):
    klines = get_klines(symbol, interval)
    if not klines: return None
    closes = [float(c[4]) for c in klines]
    volumes = [float(c[5]) for c in klines]

    price = closes[-1]
    e21 = ema(closes, 21)
    e50 = ema(closes, 50)
    e200 = ema(closes, 200)
    r = rsi(closes)
    vol_avg = sum(volumes[-20:])/20
    vol_now = volumes[-1]

    # --- PRO SCORING SYSTEM ---
    score = 0
    # 1. EMA Trend
    if e21 > e50 > e200: score += 30
    elif e21 < e50 < e200: score -= 30
    elif e21 > e50: score += 15
    else: score -= 15

    # 2. RSI
    if r > 60: score += 20
    elif r < 40: score -= 20
    elif 45 < r < 55: score += 0

    # 3. Price vs EMA
    if price > e21: score += 20
    else: score -= 20

    # 4. Volume Confirmation
    if vol_now > vol_avg*1.2: score += 10 if score>0 else -10

    # 5. Recent momentum
    if closes[-1] > closes[-5]: score += 10
    else: score -= 10

    # Final Signal
    score = max(-100, min(100, score))

    if score >= 60:
        signal = "STRONG BUY 🚀"
        confidence = f"{60 + abs(score)//2}%"
        tp = price * 1.015
        sl = price * 0.992
    elif score >= 25:
        signal = "BUY ✅"
        confidence = f"{55}%"
        tp = price * 1.008
        sl = price * 0.995
    elif score <= -60:
        signal = "STRONG SELL 🔻"
        confidence = f"{60 + abs(score)//2}%"
        tp = price * 0.985
        sl = price * 1.008
    elif score <= -25:
        signal = "SELL ❌"
        confidence = f"{55}%"
        tp = price * 0.992
        sl = price * 1.005
    else:
        signal = "WAIT ⚠️"
        confidence = "40%"
        tp = price
        sl = price

    trend = "BULLISH 🟢" if e21 > e50 else "BEARISH 🔴"
    return f"{interval} | {trend} | RSI:{r:.0f} | {signal} | Conf:{confidence}\n Price:${price:.2f} TP:${tp:.2f} SL:${sl:.2f} Score:{score}"

def make_msg():
    txt = "💎 HACKER PRO MAX v10 - LIVE\n"
    txt += "EMA21/50/200 + RSI + Volume + Momentum\n\n"
    for name, sym in SYMBOLS.items():
        txt += f"--- {name} ---\n"
        for tf in TF:
            sig = get_signal(sym, tf)
            if sig: txt += sig + "\n"
            else: txt += f"{tf} | Loading...\n"
        txt += "\n"
    txt += "⚠️ Ye financial advice nahi, confirmation ke liye 1h+4h same trend dekho"
    return txt

async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(make_msg())

def main():
    threading.Thread(target=run_flask, daemon=True).start()
    if not BOT_TOKEN: return
    requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=True", timeout=10)
    print("PRO BOT POLLING LIVE!", flush=True)
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", reply))
    app.add_handler(CommandHandler("signal", reply))
    app.add_handler(MessageHandler(filters.TEXT, reply))
    app.run_polling(drop_pending_updates=True, stop_signals=None)

if __name__ == "__main__": main()
