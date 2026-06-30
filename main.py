import os
import re
import subprocess
import requests
import telebot
from telebot import types
from flask import Flask, request, jsonify

# ========================
# SOZLAMALAR
# ========================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "https://husanboy611-videoyuklovchi.hf.space")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN muhit o'zgaruvchisi o'rnatilmagan!")

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

user_links = {}

# ========================
# YORDAMCHI FUNKSIYALAR
# ========================

def ensure_ytdlp():
    try:
        subprocess.run(["yt-dlp", "--version"], capture_output=True, check=True)
    except Exception:
        os.system("pip install -q yt-dlp --upgrade")


def upload_to_gofile(file_path):
    server_res = requests.get("https://api.gofile.io/servers", timeout=15).json()
    if server_res.get("status") == "ok":
        server_name = server_res["data"]["servers"][0]["name"]
        upload_url = f"https://{server_name}.gofile.io/contents/uploadfile"
        with open(file_path, "rb") as f:
            upload_res = requests.post(upload_url, files={"file": f}, timeout=180).json()
        if upload_res.get("status") == "ok":
            return upload_res["data"]["downloadPage"]
    raise Exception("Gofile serveriga yuklashda xatolik.")


def send_or_upload(chat_id, fayl_nomi, is_audio, status_msg_id):
    if not os.path.exists(fayl_nomi):
        bot.edit_message_text("❌ Fayl topilmadi.", chat_id, status_msg_id)
        return

    fayl_hajmi = os.path.getsize(fayl_nomi) / (1024 * 1024)

    if fayl_hajmi < 49.5:
        bot.edit_message_text("📤 Telegram'ga yuborilmoqda...", chat_id, status_msg_id)
        with open(fayl_nomi, "rb") as f:
            if is_audio:
                bot.send_audio(chat_id, f, caption="🎵 Audio tayyor!")
            else:
                bot.send_video(chat_id, f, caption="📺 Video tayyor!", supports_streaming=True)
        bot.delete_message(chat_id, status_msg_id)
    else:
        bot.edit_message_text(
            f"📦 Fayl katta ({int(fayl_hajmi)} MB). Gofile'ga yuklanmoqda... ☁️",
            chat_id, status_msg_id
        )
        direct_link = upload_to_gofile(fayl_nomi)
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📥 Yuklab olish", url=direct_link))
        bot.delete_message(chat_id, status_msg_id)
        bot.send_message(
            chat_id,
            f"🎉 Fayl tayyor! Hajmi: {int(fayl_hajmi)} MB\n"
            "Quyidagi tugma orqali yuklab oling 👇",
            reply_markup=markup
        )


def cleanup_files(chat_id):
    for ext in ["mp4", "mp3", "mkv", "webm"]:
        for path in [f"file_{chat_id}.{ext}", f"file_{chat_id}_direct.mp4"]:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass


def download_with_ytdlp(url, is_audio=False, output_path="file"):
    if is_audio:
        cmd = [
            "yt-dlp", "--no-playlist",
            "-x", "--audio-format", "mp3",
            "--audio-quality", "0",
            "-o", f"{output_path}.%(ext)s",
            "--no-warnings", "--retries", "3", url
        ]
    else:
        cmd = [
            "yt-dlp", "--no-playlist",
            "-f", "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "-o", f"{output_path}.%(ext)s",
            "--no-warnings", "--retries", "3", url
        ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise Exception(result.stderr[-500:] if result.stderr else "Yuklab bo'lmadi")

    ext = "mp3" if is_audio else "mp4"
    fpath = f"{output_path}.{ext}"
    if os.path.exists(fpath):
        return fpath

    base = os.path.basename(output_path)
    for f in os.listdir("."):
        if f.startswith(base) and os.path.isfile(f):
            return f

    raise Exception("Fayl yaratilmadi.")


def download_direct(url, output_path="file_direct.mp4"):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
        "Referer": url,
    }

    if ".m3u8" in url.lower():
        cmd = ["yt-dlp", "--no-warnings", "--merge-output-format", "mp4",
               "--retries", "3", "-o", output_path, url]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            raise Exception("M3U8 yuklab bo'lmadi: " + result.stderr[-200:])
        return output_path

    with requests.get(url, headers=headers, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
    return output_path


# ========================
# BOT HANDLERLARI
# ========================

@bot.message_handler(commands=['start'])
def welcome(message):
    bot.reply_to(
        message,
        "👋 Salom! Men universal video yuklovchi botman.\n\n"
        "📌 Qo'llab-quvvatlanadigan saytlar:\n"
        "✅ YouTube, Instagram, TikTok\n"
        "✅ VK, OK.ru, Facebook\n"
        "✅ Twitter/X, Reddit\n"
        "✅ To'g'ridan MP4/M3U8 havolalar\n\n"
        "🔗 Havolani yuboring! 🎬"
    )


@bot.message_handler(func=lambda message: True, content_types=['text'])
def get_video_info(message):
    urls = re.findall(r'(https?://\S+)', message.text)
    if not urls:
        return

    url = urls[0].rstrip('.,;)')
    user_links[message.chat.id] = url

    url_lower = url.lower()
    is_direct = any(url_lower.endswith(ext) for ext in [".mp4", ".mkv", ".avi", ".mov"]) \
                or ".m3u8" in url_lower

    if is_direct:
        status_msg = bot.reply_to(message, "🔗 To'g'ridan video topildi. Yuklanmoqda... ⏳")
        output_path = f"file_{message.chat.id}.mp4"
        try:
            fayl_nomi = download_direct(url, output_path)
            send_or_upload(message.chat.id, fayl_nomi, False, status_msg.message_id)
        except Exception as e:
            bot.edit_message_text(f"❌ Xatolik: {str(e)[:200]}", message.chat.id, status_msg.message_id)
        finally:
            cleanup_files(message.chat.id)
    else:
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("🎬 Video (MP4)", callback_data="video_dl"),
            types.InlineKeyboardButton("🎵 Audio (MP3)", callback_data="audio_dl")
        )
        bot.reply_to(message, "✅ Nima yuklamoqchisiz?", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data in ["video_dl", "audio_dl"])
def handle_download(call):
    chat_id = call.message.chat.id
    url = user_links.get(chat_id)
    if not url:
        bot.answer_callback_query(call.id, "⚠️ Havola topilmadi. Qaytadan yuboring.")
        return

    bot.answer_callback_query(call.id)
    is_audio = call.data == "audio_dl"
    status_msg = bot.send_message(chat_id, "⏳ Yuklanmoqda, iltimos kuting...")
    output_path = f"file_{chat_id}"

    try:
        bot.edit_message_text("🔄 Serverdan olinmoqda...", chat_id, status_msg.message_id)
        fayl_nomi = download_with_ytdlp(url, is_audio=is_audio, output_path=output_path)
        send_or_upload(chat_id, fayl_nomi, is_audio, status_msg.message_id)

    except subprocess.TimeoutExpired:
        bot.edit_message_text("⏱️ Vaqt tugadi. Fayl juda katta yoki internet sekin.",
                              chat_id, status_msg.message_id)
    except Exception as e:
        err = str(e)
        if any(kw in err for kw in ["Unsupported URL", "Unable to extract", "no suitable", "ERROR"]):
            try:
                bot.edit_message_text("⚠️ To'g'ridan yuklab ko'rilmoqda...", chat_id, status_msg.message_id)
                direct_path = f"file_{chat_id}_direct.mp4"
                fayl_nomi = download_direct(url, direct_path)
                send_or_upload(chat_id, fayl_nomi, False, status_msg.message_id)
            except Exception:
                bot.edit_message_text(
                    "❌ Bu saytdan yuklab bo'lmadi.\n\n"
                    "💡 Brauzerda videoni oching → o'ng klik → "
                    "'Video manzilini nusxalash' → o'sha havolani yuboring.",
                    chat_id, status_msg.message_id
                )
        else:
            bot.edit_message_text(f"❌ Xatolik: {err[:200]}", chat_id, status_msg.message_id)
    finally:
        cleanup_files(chat_id)


# ========================
# FLASK ENDPOINTLARI
# ========================

@app.route('/', methods=['GET'])
def index():
    return "✅ Video Yuklovchi Bot ishlayapti!", 200


@app.route('/webhook', methods=['POST'])
def webhook():
    """Telegram shu endpoint'ga xabar yuboradi"""
    try:
        if request.headers.get('content-type') == 'application/json':
            json_string = request.get_data().decode('utf-8')
            update = telebot.types.Update.de_json(json_string)
            bot.process_new_updates([update])
            return '', 200
        return 'Bad request', 400
    except Exception as e:
        print(f"Webhook xatolik: {e}")
        return '', 200  # Telegram uchun har doim 200 qaytaramiz


@app.route('/set_webhook', methods=['GET'])
def set_webhook():
    """Webhookni o'rnatish"""
    try:
        webhook_url = f"{WEBHOOK_URL}/webhook"
        bot.remove_webhook()
        import time
        time.sleep(1)
        result = bot.set_webhook(url=webhook_url)
        if result:
            return jsonify({
                "status": "✅ Muvaffaqiyatli!",
                "webhook_url": webhook_url
            }), 200
        return jsonify({"status": "❌ Xatolik: set_webhook False qaytardi"}), 500
    except Exception as e:
        return jsonify({"status": f"❌ Xatolik: {str(e)}"}), 500


@app.route('/check_webhook', methods=['GET'])
def check_webhook():
    """Webhook holatini tekshirish"""
    try:
        info = bot.get_webhook_info()
        return jsonify({
            "url": info.url,
            "pending_updates": info.pending_update_count,
            "last_error": info.last_error_message,
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/remove_webhook', methods=['GET'])
def remove_webhook():
    try:
        bot.remove_webhook()
        return jsonify({"status": "✅ Webhook o'chirildi"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ========================
# ISHGA TUSHIRISH
# ========================

if __name__ == "__main__":
    ensure_ytdlp()
    print("🚀 Bot ishga tushdi (Webhook rejimi)")
    print(f"📡 Space URL: {WEBHOOK_URL}")
    print("➡️  Webhook o'rnatish: GET /set_webhook")
    app.run(host="0.0.0.0", port=7860, debug=False)
