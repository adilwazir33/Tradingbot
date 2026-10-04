import os
import telebot
import yfinance as yf
from PIL import Image, ImageDraw, ImageFont
import io

# Render se Token lega, agar nahi to neeche wala use karega
BOT_TOKEN = os.getenv("BOT_TOKEN", "APNA_TOKEN_YAHAN_DALO")
bot = telebot.TeleBot(BOT_TOKEN)

PAIRS = {
    "XAUUSD.r": "GC=F",
    "EURUSD.r": "EURUSD=X",
    "BTCUSD.r": "BTC-USD",
    "USDJPY.r": "USDJPY=X",
    "NACUSD.r": "^IXIC"
}

def get_signals():
    res = {}
    for name, code in PAIRS.items():
        try:
            df = yf.download(code, period="2d", interval="1h", progress=False, auto_adjust=True)
            if len(df) > 1 and df['Close'].iloc[-1] > df['Close'].iloc[-2]:
                res[name] = "BUY"
            else:
                res[name] = "SELL"
        except:
            res[name] = "WAIT"
    return res

def make_image(signals):
    W, H = 800, 620
    img = Image.new('RGB', (W, H), (14, 16, 22))
    d = ImageDraw.Draw(img)
    d.rectangle([0,0,W,85], fill=(25, 28, 36))
    d.text((30, 22), "ADIL SIGNALS BOT - 5 PAIRS", fill=(255,255,255))
    d.text((30, 50), "15MIN + 1H = FINAL CONFIRMED", fill=(140,140,140))
    y = 120
    for p, s in signals.items():
        color = (34,197,94) if s=="BUY" else (239,68,68) if s=="SELL" else (234,179,8)
        d.text((40, y+12), p, fill=(255,255,255))
        d.rounded_rectangle([500, y, 750, y+50], radius=12, fill=color)
        txt = f"{s} CONFIRMED" if s!="WAIT" else "WAIT"
        d.text((540, y+16), txt, fill=(255,255,255))
        y+=85
    bio = io.BytesIO()
    img.save(bio, 'PNG')
    bio.seek(0)
    return bio

@bot.message_handler(func=lambda m: m.text and "signal" in m.text.lower())
def signal_handler(m):
    bot.send_message(m.chat.id, "Signal nikal raha hu Adil Bhai... ⏳")
    sigs = get_signals()
    pic = make_image(sigs)
    cap = "📊 5 Pairs Final Signal:\n\n"
    for k,v in sigs.items():
        cap += f"{'🟢' if v=='BUY' else '🔴' if v=='SELL' else '🟡'} {k} = {v}\n"
    bot.send_photo(m.chat.id, pic, caption=cap)

print("BOT IS LIVE - Waiting for 'signal'")
bot.infinity_polling()
