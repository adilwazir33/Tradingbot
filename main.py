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
    return "Live - Banking Pro Fixed"

def get_binance_data(interval):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        url = f"https://api.binance.com/api/v3/klines?symbol={SYMBOL}&interval={interval}&limit=100"
        r = requests.get(url, headers=headers, timeout=15)
        data = r.json()
        if not isinstance(data, list) or len(data) < 50:
            return None, None, None
        closes = [float(c[4]) for c in data]
        highs = [float(c[2]) for c in data]
        lows = [float(c[3]) for c in data]
        return closes, highs, lows
    except Exception as e:
        print(f"Binance Error {interval}: {e}")
        return None, None, None

def analyze_tf(name, code):
    closes, highs, lows = get_binance_data(code)
    if not closes: return None
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
    sig="LONG" if price>ema20>ema50 and 50<rsi<75 else "SHORT" if price<ema20<ema50 and 25<rsi<50 else "NO TRADE"
    return {"price":price,"signal":sig,"rsi":round(rsi,2),"tf":name}

def format_signal(d):
    if not d: return "⏳ Binance loading... 10 sec baad /signal dobara bhejo"
    p=d['price']; s=d['signal']; tf=d['tf']
    if s=="NO TRADE": return f"⏳ {tf} - BTC\nPrice: {p:.2f}\nRSI: {d['rsi']}\nStatus: NO TRADE - Wait"
    if s=="LONG":
        sl,tp1,tp2,tp3=p*0.988,p*1.012,p*1.025,p*1.04
        return f"🚀 {tf} BUY/LONG\nEntry: {p:.2f}\nTP1: {tp1:.2f} TP2: {tp2:.2f} TP3: {tp3:.2f}\nSL: {sl:.2f}\nRSI: {d['rsi']}"
    else:
        sl,tp1,tp2,tp3=p*1.012,p*0.988,p*0.975,p*0.96
        return f"🔻 {tf} SELL/SHORT\nEntry: {p:.2f}\nTP1: {tp1:.2f} TP2: {tp2:.2f} TP3: {tp3:.2f}\nSL: {sl:.2f}\nRSI: {d['rsi']}"

def full_pro():
    a=analyze_tf("15MIN","15m"); time.sleep(0.5)
    b=analyze_tf("1HOUR","1h"); time.sleep(0.5)
    c=analyze_tf("4HOUR","4h")
    if not a or not b or not c:
        return "⏳ Binance data load ho raha hai...\n10 second baad /signal dobara bhejo"
    lc=sum(1 for x in [a,b,c] if x['signal']=="LONG"); sc=sum(1 for x in [a,b,c] if x['signal']=="SHORT")
    final="BUY CONFIRMED" if lc>=2 else "SELL CONFIRMED" if sc>=2 else "WAIT - NO TRADE"
    return f"🏦 FULL BANKING PRO - BTC {a['price']:.2f}\n\n{format_signal(a)}\n---\n{format_signal(b)}\n---\n{format_signal(c)}\n\nFINAL: {final} ({lc}L vs {sc}S)"

@bot.message_handler(commands=['start'])
def start_cmd(m): bot.send_message(m.chat.id, "🏦 BANKING PRO FIXED\n/signal - Full\n/15m\n/1h\n/4h\n/price")
@bot.message_handler(commands=['signal','analysis'])
def s(m): bot.send_message(m.chat.id, full_pro())
@bot.message_handler(commands=['15m'])
def c1(m): bot.send_message(m.chat.id, format_signal(analyze_tf("15MIN","15m")))
@bot.message_handler(commands=['1h'])
def c2(m): bot.send_message(m.chat.id, format_signal(analyze_tf("1HOUR","1h")))
@bot.message_handler(commands=['4h'])
def c3(m): bot.send_message(m.chat.id, format_signal(analyze_tf("4HOUR","4h")))
@bot.message_handler(commands=['price'])
def c4(m):
    closes,_,_=get_binance_data("1m")
    if closes: bot.send_message(m.chat.id, f"BTC: {closes[-1]:.2f}")
    else: bot.send_message(m.chat.id, "Loading...")

def run_bot():
    while True:
        try: bot.infinity_polling()
        except: time.sleep(5)

if __name__=="__main__":
    Thread(target=run_bot,daemon=True).start()
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT",10000)))
