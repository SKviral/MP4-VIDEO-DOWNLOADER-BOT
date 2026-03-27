import os
import sys
import time
import aiohttp
import asyncio
import zipfile
import shutil
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

    CHUNK_SIZE = 2 * 1024 * 1024       # 2MB chunks
    MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB max
    MAX_RETRIES = 3
    VIDEO_EXTENSIONS = (".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".m4v")


    def is_zip_url(url, content_type):
        url_lower = url.lower().split("?")[0]
        return (
            url_lower.endswith(".zip")
            or "application/zip" in content_type
            or "application/x-zip" in content_type
            or "application/octet-stream" in content_type and url_lower.endswith(".zip")
        )


    def find_videos_in_zip(extract_dir):
        """ZIP এর ভেতর সব ভিডিও ফাইল খুঁজে বের করে, সাইজ অনুযায়ী সাজানো।"""
        videos = []
        for root, dirs, files in os.walk(extract_dir):
            for fname in files:
                if fname.lower().endswith(VIDEO_EXTENSIONS):
                    full_path = os.path.join(root, fname)
                    videos.append((full_path, fname))
        videos.sort(key=lambda x: os.path.getsize(x[0]), reverse=True)
        return videos


    async def download_file(url, save_path, status_msg):
        """
        ফাইল ডাউনলোড করে, progress দেখায়, retry করে।
        Returns (True, content_type) অথবা (False, error_message)
        """
        timeout = aiohttp.ClientTimeout(connect=30, sock_read=120, total=None)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        err = "অজানা সমস্যা।"
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                    async with session.get(url) as response:
                        if response.status != 200:
                            return False, f"সার্ভার {response.status} রেসপন্স দিয়েছে।"

                        content_type = response.headers.get("Content-Type", "")
                        if "text/html" in content_type:
                            return False, "এটি ডাইরেক্ট ডাউনলোড লিংক নয়, HTML পেজ।"

                        total_size = int(response.headers.get("Content-Length", 0))
                        if total_size > MAX_FILE_SIZE:
                            return False, f"ফাইলটি অনেক বড় ({total_size / (1024**3):.2f} GB)। সর্বোচ্চ ২ GB।"

                        downloaded = 0
                        last_update = time.time()

                        with open(save_path, "wb") as f:
                            async for chunk in response.content.iter_chunked(CHUNK_SIZE):
                                f.write(chunk)
                                downloaded += len(chunk)

                                now = time.time()
                                if now - last_update >= 5:
                                    last_update = now
                                    dl_mb = downloaded / (1024 * 1024)
                                    if total_size > 0:
                                        pct = (downloaded / total_size) * 100
                                        total_mb = total_size / (1024 * 1024)
                                        txt = f"⬇️ ডাউনলোড হচ্ছে...\n{dl_mb:.1f} MB / {total_mb:.1f} MB ({pct:.0f}%)"
                                    else:
                                        txt = f"⬇️ ডাউনলোড হচ্ছে... {dl_mb:.1f} MB"
                                    try:
                                        await status_msg.edit_text(txt)
                                    except Exception:
                                        pass

                        actual_size = os.path.getsize(save_path)
                        if actual_size == 0:
                            return False, "ডাউনলোড করা ফাইলটি খালি।"
                        if total_size > 0 and actual_size < total_size * 0.99:
                            return False, f"ফাইল অসম্পূর্ণ ({actual_size}/{total_size} bytes)।"

                        return True, content_type

            except aiohttp.ClientConnectorError:
                err = "সার্ভারের সাথে কানেক্ট করা যাচ্ছে না।"
            except asyncio.TimeoutError:
                err = "কানেকশন টাইমআউট হয়েছে।"
            except Exception as e:
                err = str(e)

            if attempt < MAX_RETRIES:
                try:
                    await status_msg.edit_text(
                        f"⚠️ চেষ্টা {attempt}/{MAX_RETRIES} ব্যর্থ: {err}\n🔄 আবার চেষ্টা করছি..."
                    )
                except Exception:
                    pass
                await asyncio.sleep(3)
                if os.path.exists(save_path):
                    os.remove(save_path)

        return False, f"{MAX_RETRIES} বার চেষ্টার পরও ব্যর্থ: {err}"


    @app.on_message(filters.command("start"))
    async def start_cmd(client, message: Message):
        await message.reply_text(
            "হ্যালো! 👋\n"
            "আমাকে যেকোনো ডাইরেক্ট MP4 বা ZIP (MP4 সহ) ডাউনলোড লিংক দিন।\n"
            "আমি ডাউনলোড করে ভিডিও হিসেবে পাঠিয়ে দেবো। 🎬\n\n"
            "⚠️ লিংকটি অবশ্যই ডাইরেক্ট ডাউনলোড লিংক হতে হবে।"
        )


    @app.on_message(filters.text & ~filters.command("start"))
    async def handle_url(client, message: Message):
        url = message.text.strip()

        if not (url.startswith("http://") or url.startswith("https://")):
            await message.reply_text("❌ সঠিক URL দিন (http:// বা https:// দিয়ে শুরু)।")
            return

        status_msg = await message.reply_text("⏳ লিংকটি চেক করা হচ্ছে...")

        uid = f"{message.chat.id}_{int(time.time())}"
        temp_dir = f"temp_{uid}"
        zip_path = f"{temp_dir}.zip"
        mp4_path = f"video_{uid}.mp4"
        temp_dl = f"dl_{uid}.tmp"

        try:
            await status_msg.edit_text("⬇️ ডাউনলোড শুরু হচ্ছে...")
            success, result = await download_file(url, temp_dl, status_msg)

            if not success:
                await status_msg.edit_text(f"❌ ডাউনলোড ব্যর্থ!\n{result}")
                return

            content_type = result

            # ZIP কিনা সেটা নির্ধারণ করো
            url_lower = url.lower().split("?")[0]
            is_zip = (
                url_lower.endswith(".zip")
                or "application/zip" in content_type
                or "application/x-zip" in content_type
            )

            # magic bytes দিয়েও চেক করো (PK signature)
            if not is_zip:
                with open(temp_dl, "rb") as f:
                    magic = f.read(4)
                if magic[:2] == b"PK":
                    is_zip = True

            if is_zip:
                # ZIP হ্যান্ডেল করো
                os.rename(temp_dl, zip_path)
                await status_msg.edit_text("📦 ZIP ফাইল পাওয়া গেছে। আনজিপ করা হচ্ছে...")

                try:
                    with zipfile.ZipFile(zip_path, "r") as zf:
                        # ZIP এর ভেতর ভিডিও আছে কিনা চেক
                        names = zf.namelist()
                        video_names = [n for n in names if n.lower().endswith(VIDEO_EXTENSIONS)]
                        if not video_names:
                            await status_msg.edit_text(
                                "❌ ZIP ফাইলের ভেতরে কোনো ভিডিও পাওয়া যায়নি।\n"
                                f"ফাইলগুলো: {', '.join(names[:10])}"
                            )
                            return

                        os.makedirs(temp_dir, exist_ok=True)
                        zf.extractall(temp_dir)
                except zipfile.BadZipFile:
                    await status_msg.edit_text("❌ ফাইলটি সঠিক ZIP ফরম্যাটে নেই।")
                    return

                videos = find_videos_in_zip(temp_dir)
                if not videos:
                    await status_msg.edit_text("❌ ZIP আনজিপ করার পরেও কোনো ভিডিও পাওয়া যায়নি।")
                    return

                total_videos = len(videos)
                await status_msg.edit_text(
                    f"✅ {total_videos}টি ভিডিও পাওয়া গেছে।\n⬆️ আপলোড শুরু হচ্ছে..."
                )

                for i, (video_path, video_fname) in enumerate(videos, 1):
                    size_mb = os.path.getsize(video_path) / (1024 * 1024)
                    try:
                        await status_msg.edit_text(
                            f"⬆️ আপলোড হচ্ছে ({i}/{total_videos}): {video_fname}\nআকার: {size_mb:.2f} MB"
                        )
                    except Exception:
                        pass

                    await client.send_video(
                        chat_id=message.chat.id,
                        video=video_path,
                        caption=f"🎬 {video_fname}\nআকার: {size_mb:.2f} MB ({i}/{total_videos})",
                        reply_to_message_id=message.id,
                        supports_streaming=True,
                    )

                await status_msg.delete()

            else:
                # সরাসরি MP4 বা অন্য ভিডিও
                os.rename(temp_dl, mp4_path)
                size_mb = os.path.getsize(mp4_path) / (1024 * 1024)
                await status_msg.edit_text(
                    f"✅ ডাউনলোড সম্পন্ন ({size_mb:.2f} MB)।\n⬆️ আপলোড হচ্ছে... 🚀"
                )

                await client.send_video(
                    chat_id=message.chat.id,
                    video=mp4_path,
                    caption=f"✅ ভিডিও ডাউনলোড সম্পন্ন!\nআকার: {size_mb:.2f} MB",
                    reply_to_message_id=message.id,
                    supports_streaming=True,
                )

                await status_msg.delete()

        except Exception as e:
            print(f"Error: {e}", flush=True)
            traceback.print_exc()
            try:
                await status_msg.edit_text(f"⚠️ একটি সমস্যা হয়েছে:\n{str(e)}")
            except Exception:
                pass
        finally:
            # সব টেম্প ফাইল মুছে ফেলো
            for path in [temp_dl, zip_path, mp4_path]:
                if path and os.path.exists(path):
                    os.remove(path)
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)


    if __name__ == "__main__":
        keep_alive()
        print("✅ Bot is successfully running...", flush=True)
        app.run()

except Exception as e:
    print("❌ CRITICAL ERROR:", flush=True)
    traceback.print_exc()
    sys.exit(1)
