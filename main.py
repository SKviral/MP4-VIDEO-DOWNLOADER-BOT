import os
import sys
import time
import aiohttp
import traceback
from pyrogram import Client, filters
from pyrogram.types import Message
from keep_alive import keep_alive

print("⏳ Bot starting...", flush=True)

try:
    # Environment Variables চেক করা
    API_ID_STR = os.environ.get("API_ID", "").strip()
    API_HASH = os.environ.get("API_HASH", "").strip()
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()

    if not API_ID_STR or not API_HASH or not BOT_TOKEN:
        print("❌ ERROR: Render এর Environment Variables এ API_ID, API_HASH বা BOT_TOKEN বসানো নেই!", flush=True)
        sys.exit(1)

    try:
        API_ID = int(API_ID_STR)
    except ValueError:
        print("❌ ERROR: API_ID শুধুমাত্র সংখ্যা হতে হবে! কোনো স্পেস বা অক্ষর থাকা যাবে না।", flush=True)
        sys.exit(1)

    # Bot Setup
    app = Client("video_downloader", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

    async def download_file(url, file_name):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    response.raise_for_status()
                    with open(file_name, 'wb') as f:
                        async for chunk in response.content.iter_chunked(1024 * 1024):
                            f.write(chunk)
            return True
        except Exception as e:
            print(f"Download Error: {e}", flush=True)
            return False

    @app.on_message(filters.command("start"))
    async def start_cmd(client, message: Message):
        await message.reply_text(
            "হ্যালো! 👋\nআমাকে যেকোনো ডাইরেক্ট MP4 ডাউনলোড লিংক দিন। আমি সেটি ডাউনলোড করে আপনাকে ভিডিও হিসেবে পাঠিয়ে দেবো।"
        )

    @app.on_message(filters.text & ~filters.command("start"))
    async def handle_url(client, message: Message):
        url = message.text.strip()
        
        if not (url.startswith("http://") or url.startswith("https://")):
            await message.reply_text("❌ অনুগ্রহ করে একটি সঠিক URL দিন।")
            return

        status_msg = await message.reply_text("⏳ আপনার লিংকটি চেক করা হচ্ছে...")
        file_name = f"video_{message.chat.id}_{int(time.time())}.mp4"
        
        try:
            await status_msg.edit_text("⬇️ ভিডিওটি Render সার্ভারে ডাউনলোড হচ্ছে...\n(অপেক্ষা করুন)")
            
            success = await download_file(url, file_name)
            
            if not success:
                await status_msg.edit_text("❌ ডাউনলোড ব্যর্থ হয়েছে! লিংকটি ডাইরেক্ট ডাউনলোড লিংক কিনা তা চেক করুন।")
                return
            
            file_size_mb = os.path.getsize(file_name) / (1024 * 1024)
            await status_msg.edit_text(f"⬆️ ডাউনলোড সম্পন্ন ({file_size_mb:.2f} MB)।\nএবার টেলিগ্রামে আপলোড করা হচ্ছে... 🚀")
            
            await client.send_video(
                chat_id=message.chat.id,
                video=file_name,
                caption=f"✅ আপনার ভিডিও ডাউনলোড সম্পন্ন হয়েছে!\nFile Size: {file_size_mb:.2f} MB",
                reply_to_message_id=message.id,
                supports_streaming=True
            )
            
            await status_msg.delete()
            
        except Exception as e:
            await status_msg.edit_text(f"⚠️ একটি সমস্যা হয়েছে: {str(e)}")
        finally:
            if os.path.exists(file_name):
                os.remove(file_name)

    if __name__ == "__main__":
        keep_alive()
        print("✅ Bot is successfully running on Render...", flush=True)
        app.run()

except Exception as e:
    print("❌ CRITICAL ERROR:", flush=True)
    traceback.print_exc()
    sys.exit(1)# ... (বাকি কোড আগের মতোই থাকবে, যেমন async def download_file থেকে শুরু করে শেষ পর্যন্ত) ...
