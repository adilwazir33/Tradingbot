import ccxt, telebot, os
from flask import Flask
import threading
BOT=os.environ.get("BOT_TOKEN")
app=Flask(__name__)
ex=ccxt.okx({'enableRateLimit':True})
bot=telebot.TeleBot(BOT)
def ema(p,n):
 k=2/(n+1);e=p[0]
 for x in p[1:]:e=x*k+e*(1-k)
 return e
def sig():
 c15=[x[4] for x in ex.fetch_ohlcv('BTC/USDT','15m',limit=60)]
 c1h=[x[4] for x in ex.fetch_ohlcv('BTC/USDT','1h',limit=60)]
 c4h=[x[4] for x in ex.fetch_ohlcv('BTC/USDT','4h',limit=60)]
 pr=c15[-1];e15=ema(c15,50);e1h=ema(c1h,50);e4h=ema(c4h,50)
 if pr>e15 and pr>e1h and pr>e4h:return f"✅ LONG BTC {pr:.2f}"
 elif pr<e15 and pr<e1h and pr<e4h:return f"🔴 SHORT BTC {pr:.2f}"
 else:return f"⏳ NO TRADE {pr:.2f}"
@bot.message_handler(commands=['start','signal'])
def h(m):bot.reply_to(m,sig())
@app.route('/')
def ho():return "Live"
threading.Thread(target=lambda:bot.infinity_polling()).start()
app.run(host="0.0.0.0",port=int(os.environ.get("PORT",10000)))
