import os
import subprocess
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
from yt_dlp import YoutubeDL
from typing import Dict
import signal

# נוצר ע"י @the_joker121 בטלגרם. לערוץ https://t.me/bot_sratim_sdarot
# אל תמחק את הקרדיט הזה🥹
# לבוט דוגמא חפש בטלגרם @Music_Yt_RoBot

import os
TOKEN = os.getenv('TOKEN')

AUDIO_CACHE_CHANNEL = int(os.getenv('AUDIO_CACHE_CHANNEL'))

COOKIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cookies.txt')

message_searches = {}

audio_cache = {}

active_downloads: Dict[int, Dict] = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('שלום! שלח לי שם של שיר ואחפש אותו ביוטיוב.\n\nלקבוצה שלי👇\nhttps://t.me/+LceT_sT3WK0xZmM0',
                                  reply_to_message_id=update.message.message_id)

async def search_song(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text
    message_id = update.message.message_id
    
    ydl_opts = {
        'quiet': False,
        'no_warnings': False,
        'extract_flat': True,
        'default_search': 'ytsearch50',
        'cookies': COOKIES_FILE,
        'verbose': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-us,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1',
            'Connection': 'keep-alive',
        }
    }
    
    try:
        
        with YoutubeDL(ydl_opts) as ydl:
            results = await asyncio.get_event_loop().run_in_executor(
                None, 
                lambda: ydl.extract_info(f"ytsearch50:{query}", download=False)['entries']
            )
            
            if not results:
                await update.message.reply_text("לא נמצאו תוצאות לחיפוש זה.",
                                              reply_to_message_id=update.message.message_id)
                return
                
            message_searches[message_id] = {
                'results': results,
                'page': 0,
                'query': query,
                'original_message_id': update.message.message_id
            }
            
            await show_results_page(update.message, message_id)
    except Exception as e:
        await update.message.reply_text(f"התרחשה שגיאה בחיפוש: {str(e)}",
                                      reply_to_message_id=update.message.message_id)

async def show_results_page(message, message_id, edit=False):
    search_data = message_searches[message_id]
    results = search_data['results']
    page = search_data['page']
    original_message_id = search_data['original_message_id']
    
    start_idx = page * 10
    end_idx = min(start_idx + 10, len(results))
    current_results = results[start_idx:end_idx]
    
    keyboard = []
    for idx, video in enumerate(current_results, start=1):
        title = video['title'][:50] + "..." if len(video['title']) > 50 else video['title']
        keyboard.append([InlineKeyboardButton(f"{idx}. {title}", 
                                            callback_data=f"download_{video['id']}_{message_id}")])
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ הקודם", callback_data=f"prev_page_{message_id}"))
    if end_idx < len(results):
        nav_buttons.append(InlineKeyboardButton("הבא ➡️", callback_data=f"next_page_{message_id}"))
    if nav_buttons:
        keyboard.append(nav_buttons)

    total_pages = (len(results) + 9) // 10
    page_indicator = InlineKeyboardButton(f"❌ סגור הודעה || 📄 עמוד {page + 1}/{total_pages}", callback_data=f"close_{message_id}")
    keyboard.append([page_indicator])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = f"תוצאות שנמצאו ל: '{search_data['query']}'"
    
    if edit:
        await message.edit_text(text, reply_markup=reply_markup)
    else:
        await message.reply_text(text, 
                               reply_markup=reply_markup,
                               reply_to_message_id=original_message_id)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data_parts = query.data.split('_')
    
    if query.data.startswith("close"):
        message_id = int(data_parts[1])
        if message_id in message_searches:
            del message_searches[message_id]
        await query.message.delete()
        return
    
    if query.data.startswith("next_page"):
        message_id = int(data_parts[2])
        message_searches[message_id]['page'] += 1
        await show_results_page(query.message, message_id, edit=True)
    
    elif query.data.startswith("prev_page"):
        message_id = int(data_parts[2])
        message_searches[message_id]['page'] -= 1
        await show_results_page(query.message, message_id, edit=True)
    
    elif query.data.startswith("download"):
        video_id = data_parts[1]
        message_id = int(data_parts[2])
        user_id = query.from_user.id
        
        if user_id in active_downloads:
            await query.answer("יש לך הורדה פעילה כרגע. אנא המתן לסיומה או בטל אותה.", show_alert=True)
            return
            
        keyboard = [[InlineKeyboardButton("❌ ביטול הורדה", callback_data=f"cancel_{user_id}_{video_id}")]]
        await query.message.edit_text(
            "מוריד את השיר, אנא המתן...",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        download_info = {
            'video_id': video_id,
            'status_message': query.message,
            'original_message_id': message_searches[message_id]['original_message_id'],
            'query_message': query.message,
            'process': None,
            'filename': None
        }
        active_downloads[user_id] = download_info
        
        asyncio.create_task(
            download_and_send_song(query, context.bot, download_info)
        )
    
    elif query.data.startswith("cancel"):
        user_id = int(data_parts[1])
        video_id = data_parts[2]
        
        if query.from_user.id != user_id:
            await query.answer("אתה לא יכול לבטל הורדה של משתמש אחר", show_alert=True)
            return
            
        if user_id in active_downloads:
            
            download_info = active_downloads[user_id]
            if download_info['process']:
                try:
                    os.kill(download_info['process'].pid, signal.SIGTERM)
                except:
                    pass
            
            if download_info['filename'] and os.path.exists(download_info['filename']):
                try:
                    os.remove(download_info['filename'])
                except:
                    pass
            
            await download_info['status_message'].edit_text("ההורדה בוטלה.")
            del active_downloads[user_id]
    
    await query.answer()

async def download_and_send_song(query, bot, download_info):
    user_id = query.from_user.id
    video_id = download_info['video_id']
    status_message = download_info['status_message']
    original_message_id = download_info['original_message_id']
    
    try:
        
        if video_id in audio_cache:
            cached_message_id = audio_cache[video_id]
            try:
                await bot.copy_message(
                    chat_id=query.message.chat_id,
                    from_chat_id=AUDIO_CACHE_CHANNEL,
                    message_id=cached_message_id,
                    reply_to_message_id=original_message_id
                )
                await status_message.delete()
                return
            except Exception:
                del audio_cache[video_id]
        
        link = f"https://www.youtube.com/watch?v={video_id}"

        process = await asyncio.create_subprocess_exec(
            'yt-dlp',
            '--cookies', COOKIES_FILE,
            '--get-title',
            '--get-duration',
            link,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        download_info['process'] = process
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            raise Exception(f"שגיאה בקבלת מידע: {stderr.decode()}")

        song_info = stdout.decode().strip().split('\n')
        song_title = song_info[0]
        duration = song_info[1] if len(song_info) > 1 else "N/A"
        
        clean_title = song_title.replace('"', '')
        download_info['filename'] = f"{clean_title}.mp3"

        process = await asyncio.create_subprocess_exec(
            'yt-dlp',
            '--cookies', COOKIES_FILE,
            '-x', '--audio-format', 'mp3',
            '-o', download_info['filename'],
            link
        )
        download_info['process'] = process
        await process.communicate()
        
        if process.returncode != 0:
            raise Exception("שגיאה בהורדת השיר")

        if not os.path.exists(download_info['filename']):
            raise Exception("הקובץ לא נוצר")

        
        caption = f"🎵 שם: {clean_title}\n" \
                 f"⏱ משך: {duration}\n\n" \
                 f"Uploaded by @Music_Yt_RoBot"
        
        with open(download_info['filename'], 'rb') as audio_file:
            cache_message = await bot.send_audio(
                chat_id=AUDIO_CACHE_CHANNEL,
                audio=audio_file,
                caption=caption,
                title=clean_title
            )
            
            audio_cache[video_id] = cache_message.message_id
            
            await bot.copy_message(
                chat_id=query.message.chat_id,
                from_chat_id=AUDIO_CACHE_CHANNEL,
                message_id=cache_message.message_id,
                reply_to_message_id=original_message_id
            )
        
        # ניקוי
        if os.path.exists(download_info['filename']):
            os.remove(download_info['filename'])
        await status_message.delete()
            
    except asyncio.CancelledError:
        await status_message.edit_text("ההורדה בוטלה.")
        if download_info['filename'] and os.path.exists(download_info['filename']):
            os.remove(download_info['filename'])
            
    except Exception as e:
        await status_message.edit_text(f"התרחשה שגיאה בהורדת השיר: {str(e)}")
        
    finally:
        if user_id in active_downloads:
            del active_downloads[user_id]
        
        if download_info['filename'] and os.path.exists(download_info['filename']):
            try:
                os.remove(download_info['filename'])
            except:
                pass

def main():
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_song))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    print("הבוט התחיל לפעול...")
    application.run_polling()

if __name__ == '__main__':
    main()

# נוצר ע"י @the_joker121 בטלגרם. לערוץ https://t.me/bot_sratim_sdarot
# אל תמחק את הקרדיט הזה🥹
# לבוט דוגמא חפש בטלגרם @Music_Yt_RoBot
