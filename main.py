import os
import requests
import time
from flask import Flask
from threading import Thread

app = Flask(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
print(f"BOT_TOKEN exists: {bool(BOT_TOKEN)}")

# Bot import only if token exists
if BOT_TOKEN:
    import telebot
    bot = telebot.TeleBot(BOT_TOKEN)
    SYMBOL = "BTCUSDT"

    def get_data(interval):
        try:
            url = f"https://data-api.binance.vision/api/v3/klines?symbol={SYMBOL}&interval={interval}&limit=100"
            r = requests.get(url, timeout=10).json()
            if not isinstance(r, list): return None
            return [float(x[4]) for x in r]
        except:
            return None

    def analyze(tf_code, tf_name):
        closes = get_data(tf_code)
        if not closes or len(closes) < 50: return None
        price = closes[-1]
        ema20 = sum(closes[-20:])/20
        ema50 = sum(closes[-50:])/50
        gains=[]; losses=[]
        for i in range(1,15):
            d=closes[-i]-closes[-i-1]
            (gains if d>0 else losses).append(abs(d))
        ag=sum(gains)/14 if gains else 0.01
        al=sum(losses)/14 if losses else 0.01
        rsi=100-(100/(1+ag/al))
        sig="LONG" if price>ema20>ema50 and 55<rsi<75 else "SHORT" if price<ema20<ema50 and 25<rsi<45 else "NO TRADE"
        return {"tf":tf_name,"price":price,"sig":sig,"rsi":round(rsi,1)}

    def format_one(d):
        if not d: return "⏳ Loading... 5 sec baad /signal"
        p=d['price']; tf=d['tf']
        if d['sig']=="NO TRADE": return f"⏳ {tf} BTC {p:.2f} RSI:{d['rsi']} WAIT"
        if d['sig']=="LONG":
            sl,tp1=p*0.988,p*1.012
            return f"🚀 {tf} BUY {p:.2f} TP:{tp1:.2f} SL:{sl:.2f} RSI:{d['rsi']}"
        else:
            sl,tp1=p*1.012,p*0.988
            return f"🔻 {tf} SELL {p:.2f} TP:{tp1:.2f} SL:{sl:.2f} RSI:{d['rsi']}"

    def full_report():
        a=analyze("15m","15MIN"); time.sleep(0.3)
        b=analyze("1h","1HOUR"); time.sleep(0.3)
        c=analyze("4h","4HOUR")
        if not a or not b or not c: return "⏳ 10 sec baad /signal bhejo"
        longs=sum(1 for x in [a,b,c] if x['sig']=="LONG")
        shorts=sum(1 for x in [a,b,c] if x['sig']=="SHORT")
        final="BUY CONFIRMED" if longs>=2 else "SELL CONFIRMED" if shorts>=2 else "WAIT"
        return f"🏦 FULL PRO BTC {a['price']:.2f}\n\n{format_one(a)}\n---\n{format_one(b)}\n---\n{format_one(c)}\n\nFINAL: {final}"

    @bot.message_handler(commands=['start'])
    def start(m): bot.send_message(m.chat.id, "🏦 1000% Ready /signal")

    @bot.message_handler(commands=['signal'])
    def sig(m): bot.send_message(m.chat.id, full_report())

    @bot.message_handler(commands=['15m','1h','4h','price'])
    def all_cmd(m):
        txt=m.text
        if '15m' in txt: bot.send_message(m.chat.id, format_one(analyze("15m","15MIN")))
        elif '1h' in txt: bot.send_message(m.chat.id, format_one(analyze("1h","1HOUR")))
        elif '4h' in txt: bot.send_message(m.chat.id, format_one(analyze("4h","4HOUR")))
        else:
            c=get_data("1m")
            if c: bot.send_message(m.chat.id, f"BTC: {c[-1]:.2f}")

    def run_bot():
        while True:
            try: bot.infinity_polling()
            except Exception as e:
                print(f"Bot error: {e}"); time.sleep(5)

    Thread(target=run_bot, daemon=True).start()

@app.route('/')
def home():
    return "Bot is Live - 1000% Working"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
