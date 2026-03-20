import os
import time
import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message
from keep_alive import keep_alive

# Environment Variable থেকে ডেটা নেওয়া হচ্ছে (সিকিউরিটির জন্য)
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

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
        print(f"Download Error: {e}")
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
    print("Bot is successfully running on Render...")
    app.run()
