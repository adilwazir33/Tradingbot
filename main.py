import os, threading
from flask import Flask
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import yfinance as yf
from PIL import Image, ImageDraw, ImageFont
import io

BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

@app.route('/')
def home():
    return "Adil Bot LIVE"

# 5 Pairs
PAIRS = {
    "XAUUSD.r": "GC=F",
    "EURUSD.r": "EURUSD=X",
    "BTCUSD.r": "BTC-USD",
    "USDJPY.r": "JPY=X",
    "NACUSD.r": "^IXIC"
}

def get_signal(ticker, tf="1H"):
    try:
        interval = "15m" if tf=="15m" else "1h" if tf=="1H" else "4h"
        period = "5d" if tf=="15m" else "1mo"
        hist = yf.Ticker(ticker).history(period=period, interval=interval)
        if len(hist) < 30:
            hist = yf.Ticker(ticker).history(period="1mo", interval="1h")
        if len(hist) < 2:
            return "WAIT"
        close = hist['Close']
        last = close.iloc[-1]
        sma = close.rolling(20).mean().iloc[-1]
        if last > sma: return "BUY"
        elif last < sma: return "SELL"
        else: return "WAIT"
    except:
        return "WAIT"

def make_image(signals, tf):
    W, H = 800, 620
    # Dark background like your pic
    img = Image.new('RGB', (W, H), (13, 17, 28))
    draw = ImageDraw.Draw(img)

    # Header
    draw.rectangle([0, 0, W, 80], fill=(22, 26, 40))
    try:
        font_b = ImageFont.truetype("arialbd.ttf", 28)
        font_r = ImageFont.truetype("arial.ttf", 22)
    except:
        font_b = ImageFont.load_default()
        font_r = ImageFont.load_default()

    draw.text((30, 25), f"ADIL SIGNALS - {tf} - 5 PAIRS", fill=(255,255,255), font=font_b)

    y = 110
    for pair, sig in signals.items():
        # Pair box left
        draw.rounded_rectangle([20, y, 460, y+75], radius=18, fill=(32, 38, 58))
        draw.text((40, y+22), pair, fill=(220, 230, 255), font=font_b)

        # Signal box right - color like your pic
        if sig == "BUY":
            col = (0, 230, 118) # Green
            txt_col = (0, 0, 0)
        elif sig == "SELL":
            col = (255, 71, 87) # Red
            txt_col = (255, 255, 255)
        else: # WAIT
            col = (255, 45, 45) # Red like your pic for WAIT
            txt_col = (255, 255, 255)

        draw.rounded_rectangle([480, y, 770, y+75], radius=18, fill=col)
        draw.text((500, y+22), f"{sig} CONFIRMED", fill=txt_col, font=font_b)
        y += 95

    draw.text((25, H-30), f"Timeframe: {tf} | Powered by ADIL BOT", fill=(120,130,150), font=font_r)

    bio = io.BytesIO()
    img.save(bio, 'PNG')
    bio.seek(0)
    return bio

@bot.message_handler(func=lambda m: "signal" in m.text.lower())
def handle_signal(m):
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("15 MIN", callback_data="TF_15m"),
        InlineKeyboardButton("1 HOUR", callback_data="TF_1H"),
        InlineKeyboardButton("4 HOUR", callback_data="TF_4H")
    )
    bot.send_message(m.chat.id, "Adil Bhai Timeframe Select Karo 👇", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("TF_"))
def callback_tf(call):
    tf = call.data.split("_")[1]
    bot.answer_callback_query(call.id, f"{tf} ka signal nikal raha hu...")
    bot.send_message(call.message.chat.id, f"📊 {tf} ka signal nikal raha hu ⏳")
    sigs = {p: get_signal(t, tf) for p, t in PAIRS.items()}
    img = make_image(sigs, tf)
    bot.send_photo(call.message.chat.id, img, caption=f"⏱ {tf} Signals\n" + "\n".join([f"{k}: {v}" for k,v in sigs.items()]))

def run_bot():
    bot.infinity_polling()

if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
