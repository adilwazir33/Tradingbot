import os, threading
from flask import Flask
import telebot
import yfinance as yf
from PIL import Image, ImageDraw
import io

BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)

# Ye port wala error khatam karega
app = Flask(__name__)
@app.route('/')
def home():
    return "Adil Bot LIVE hai!"

PAIRS = {"XAUUSD.r":"GC=F","EURUSD.r":"EURUSD=X","BTCUSD.r":"BTC-USD","USDJPY.r":"USDJPY=X","NACUSD.r":"^IXIC"}

def get_signals():
    res={}
    for name, code in PAIRS.items():
        try:
            df = yf.download(code, period="2d", interval="1h", progress=False, auto_adjust=True)
            res[name] = "BUY" if df['Close'].iloc[-1] > df['Close'].iloc[-2] else "SELL"
        except:
            res[name]="WAIT"
    return res

def make_image(signals):
    W,H=800,620
    img=Image.new('RGB',(W,H),(14,16,22))
    d=ImageDraw.Draw(img)
    d.rectangle([0,0,W,85],fill=(25,28,36))
    d.text((30,22),"ADIL SIGNALS BOT - 5 PAIRS",fill=(255,255,255))
    y=120
    for p,s in signals.items():
        color=(34,197,94) if s=="BUY" else (239,68,68)
        d.text((40,y+12),p,fill=(255,255,255))
        d.rounded_rectangle([500,y,750,y+50],radius=12,fill=color)
        d.text((540,y+16),f"{s} CONFIRMED",fill=(255,255,255))
        y+=85
    bio=io.BytesIO()
    img.save(bio,'PNG')
    bio.seek(0)
    return bio

@bot.message_handler(func=lambda m: "signal" in m.text.lower())
def signal_handler(m):
    bot.send_message(m.chat.id,"Signal nikal raha hu... ⏳")
    sigs=get_signals()
    pic=make_image(sigs)
    cap="\n".join([f"{k} = {v}" for k,v in sigs.items()])
    bot.send_photo(m.chat.id,pic,caption=cap)

def run_bot():
    bot.infinity_polling()

if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
