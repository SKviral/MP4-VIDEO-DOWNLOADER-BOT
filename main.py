import os
import sys
import time
import aiohttp
import asyncio
import traceback
from pyrogram import Client, filters
from pyrogram.types import Message
from keep_alive import keep_alive

print("⏳ Bot starting...", flush=True)

try:
    API_ID_STR = os.environ.get("API_ID", "").strip()
    API_HASH = os.environ.get("API_HASH", "").strip()
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()

    if not API_ID_STR or not API_HASH or not BOT_TOKEN:
        print("❌ ERROR: API_ID, API_HASH বা BOT_TOKEN সেট করা নেই!", flush=True)
        sys.exit(1)

    try:
        API_ID = int(API_ID_STR)
    except ValueError:
        print("❌ ERROR: API_ID শুধুমাত্র সংখ্যা হতে হবে!", flush=True)
        sys.exit(1)

    app = Client("video_downloader", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

    CHUNK_SIZE = 2 * 1024 * 1024  # 2MB chunks
    MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB max (Telegram limit)
    MAX_RETRIES = 3

    async def download_file(url, file_name, status_msg):
        """
        ফাইল ডাউনলোড করে, progress দেখায়, retry করে।
        Returns (True, file_size_mb) অথবা (False, error_message)
        """
        timeout = aiohttp.ClientTimeout(
            connect=30,
            sock_read=120,
            total=None  # বড় ফাইলের জন্য total timeout নেই
        )
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                    async with session.get(url) as response:
                        if response.status != 200:
                            return False, f"সার্ভার {response.status} রেসপন্স দিয়েছে।"

                        # Content-Type চেক
                        content_type = response.headers.get("Content-Type", "")
                        if "text/html" in content_type:
                            return False, "এটি ডাইরেক্ট ডাউনলোড লিংক নয়, HTML পেজ।"

                        total_size = int(response.headers.get("Content-Length", 0))

                        if total_size > MAX_FILE_SIZE:
                            return False, f"ফাইলটি অনেক বড় ({total_size / (1024**3):.2f} GB)। সর্বোচ্চ ২ GB সাপোর্ট করা হয়।"

                        downloaded = 0
                        last_update_time = time.time()

                        with open(file_name, 'wb') as f:
                            async for chunk in response.content.iter_chunked(CHUNK_SIZE):
                                f.write(chunk)
                                downloaded += len(chunk)

                                # প্রতি ৫ সেকেন্ডে progress আপডেট
                                now = time.time()
                                if now - last_update_time >= 5:
                                    last_update_time = now
                                    if total_size > 0:
                                        percent = (downloaded / total_size) * 100
                                        dl_mb = downloaded / (1024 * 1024)
                                        total_mb = total_size / (1024 * 1024)
                                        try:
                                            await status_msg.edit_text(
                                                f"⬇️ ডাউনলোড হচ্ছে...\n"
                                                f"{dl_mb:.1f} MB / {total_mb:.1f} MB ({percent:.0f}%)"
                                            )
                                        except Exception:
                                            pass
                                    else:
                                        dl_mb = downloaded / (1024 * 1024)
                                        try:
                                            await status_msg.edit_text(
                                                f"⬇️ ডাউনলোড হচ্ছে... {dl_mb:.1f} MB"
                                            )
                                        except Exception:
                                            pass

                        # ফাইল সঠিকভাবে ডাউনলোড হয়েছে কিনা চেক
                        actual_size = os.path.getsize(file_name)
                        if actual_size == 0:
                            return False, "ডাউনলোড করা ফাইলটি খালি।"

                        if total_size > 0 and actual_size < total_size * 0.99:
                            return False, f"ফাইল অসম্পূর্ণ ({actual_size}/{total_size} bytes)।"

                        return True, actual_size / (1024 * 1024)

            except aiohttp.ClientConnectorError:
                err = "সার্ভারের সাথে কানেক্ট করা যাচ্ছে না।"
            except asyncio.TimeoutError:
                err = "কানেকশন টাইমআউট হয়েছে।"
            except Exception as e:
                err = str(e)

            if attempt < MAX_RETRIES:
                try:
                    await status_msg.edit_text(
                        f"⚠️ চেষ্টা {attempt}/{MAX_RETRIES} ব্যর্থ: {err}\n🔄 আবার চেষ্টা করা হচ্ছে..."
                    )
                except Exception:
                    pass
                await asyncio.sleep(3)

                # অসম্পূর্ণ ফাইল মুছে ফেলো
                if os.path.exists(file_name):
                    os.remove(file_name)

        return False, f"{MAX_RETRIES} বার চেষ্টার পরও ডাউনলোড ব্যর্থ হয়েছে: {err}"


    @app.on_message(filters.command("start"))
    async def start_cmd(client, message: Message):
        await message.reply_text(
            "হ্যালো! 👋\n"
            "আমাকে যেকোনো ডাইরেক্ট MP4 ডাউনলোড লিংক দিন।\n"
            "আমি সেটি ডাউনলোড করে আপনাকে ভিডিও হিসেবে পাঠিয়ে দেবো।\n\n"
            "⚠️ লিংকটি অবশ্যই .mp4 বা ভিডিওর ডাইরেক্ট লিংক হতে হবে।"
        )

    @app.on_message(filters.text & ~filters.command("start"))
    async def handle_url(client, message: Message):
        url = message.text.strip()

        if not (url.startswith("http://") or url.startswith("https://")):
            await message.reply_text("❌ অনুগ্রহ করে একটি সঠিক URL দিন (http:// বা https:// দিয়ে শুরু হতে হবে)।")
            return

        status_msg = await message.reply_text("⏳ লিংকটি চেক করা হচ্ছে...")
        file_name = f"video_{message.chat.id}_{int(time.time())}.mp4"

        try:
            await status_msg.edit_text("⬇️ ডাউনলোড শুরু হচ্ছে...")

            success, result = await download_file(url, file_name, status_msg)

            if not success:
                await status_msg.edit_text(f"❌ ডাউনলোড ব্যর্থ!\n{result}")
                return

            file_size_mb = result
            await status_msg.edit_text(
                f"✅ ডাউনলোড সম্পন্ন ({file_size_mb:.2f} MB)।\n"
                f"⬆️ টেলিগ্রামে আপলোড হচ্ছে... 🚀"
            )

            await client.send_video(
                chat_id=message.chat.id,
                video=file_name,
                caption=f"✅ ভিডিও ডাউনলোড সম্পন্ন!\nআকার: {file_size_mb:.2f} MB",
                reply_to_message_id=message.id,
                supports_streaming=True,
            )

            await status_msg.delete()

        except Exception as e:
            print(f"Error in handle_url: {e}", flush=True)
            traceback.print_exc()
            try:
                await status_msg.edit_text(f"⚠️ একটি সমস্যা হয়েছে:\n{str(e)}")
            except Exception:
                pass
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
    sys.exit(1)
