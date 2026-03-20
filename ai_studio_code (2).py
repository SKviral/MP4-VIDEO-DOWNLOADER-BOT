import os
import time
import sys
import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message
from keep_alive import keep_alive

# Environment Variable থেকে ডেটা নেওয়া হচ্ছে
try:
    API_ID = int(os.environ.get("API_ID", 0))
except ValueError:
    print("❌ Error: API_ID সংখ্যায় নেই! দয়া করে Render এ API_ID ঠিক করুন।")
    sys.exit(1)

API_HASH = os.environ.get("API_HASH", "").strip()
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()

# ভ্যারিয়েবল চেক করা হচ্ছে
if API_ID == 0 or not API_HASH or not BOT_TOKEN:
    print("❌ Error: API_ID, API_HASH বা BOT_TOKEN পাওয়া যায়নি! Render Environment এ এগুলো ঠিকমতো বসান।")
    sys.exit(1)

# বট ক্লায়েন্ট তৈরি
app = Client("video_downloader", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ... (বাকি কোড আগের মতোই থাকবে, যেমন async def download_file থেকে শুরু করে শেষ পর্যন্ত) ...