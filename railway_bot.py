import os
import io
import datetime
import re
from dotenv import load_dotenv
import telebot
from openai import OpenAI
from google.oauth2 import service_account
from googleapiclient.discovery import build
from PIL import Image

# Загружаем переменные окружения
load_dotenv()

# Получаем токены
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

if not TELEGRAM_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError('Необходимо задать TELEGRAM_TOKEN и OPENAI_API_KEY')

bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = OpenAI(api_key=OPENAI_API_KEY)

SYSTEM_PROMPT = (
    "Приведи входные данные к следующей структуре: "
    "**Дата и Время:**, **Тип транспортного средства:**, **Откуда:**, **Куда:**, "
    "**Кол-во пассажиров:**, **Телефон пассажиров:**, **Имя пассажиров:**, **Дополнительно:**. "
    "Используй ТОЛЬКО данные из исходного текста. Если информация неразборчива - пиши 'не указано'. "
    "Для даты используй формат ДД.ММ.ГГГГ, для времени ЧЧ:ММ. "
    "В поле Дополнительно включай детское кресло, бустер, багаж если упоминается."
)

def ask_openai(user_message: str) -> str:
    """Отправляет запрос в OpenAI"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message}
            ],
            max_tokens=1000,
            temperature=0.1
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Ошибка OpenAI: {str(e)}"

def extract_text_from_image_railway(image_file):
    """Извлекает текст из изображения через OpenAI Vision"""
    try:
        image = Image.open(image_file)
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='PNG')
        img_byte_arr = img_byte_arr.getvalue()
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Извлеки весь текст с изображения"},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{img_byte_arr.hex()}"}
                        }
                    ]
                }
            ],
            max_tokens=1000
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Ошибка OCR: {e}"

def smart_date_parsing(reply_text, original_text):
    """Парсинг даты из ответа бота"""
    import datetime
    import re
    
    # Ищем в ответе бота (приоритет)
    search_texts = [
        ('bot_reply', reply_text.replace('**', '').replace('*', '')),
        ('original_text', original_text)
    ]
    
    date_pattern = r'(\d{1,2}\.\d{1,2}\.\d{2,4})'
    time_pattern = r'(\d{1,2}:\d{2})'
    
    for text_name, full_text in search_texts:
        date_match = re.search(date_pattern, full_text)
        time_match = re.search(time_pattern, full_text)
        
        if date_match and time_match:
            return {
                'date_str': date_match.group(1),
                'time_str': time_match.group(1),
                'found_in': text_name
            }
    
    return None

def add_event_to_calendar(event_data):
    """Создает событие в Google Calendar"""
    try:
        SCOPES = ['https://www.googleapis.com/auth/calendar']
        SERVICE_ACCOUNT_FILE = 'lively-vim-467215-i4-cd77f5dc7f2f.json'
        calendar_id = 'slavka0990slavka@gmail.com'

        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        service = build('calendar', 'v3', credentials=credentials)
        
        # Создаем основное событие
        main_event = {
            'summary': event_data['summary'],
            'description': event_data['description'],
            'start': {'dateTime': event_data['start'], 'timeZone': 'Europe/Minsk'},
            'end': {'dateTime': event_data['end'], 'timeZone': 'Europe/Minsk'},
            'reminders': {'useDefault': False, 'overrides': []}
        }
        
        created_event = service.events().insert(calendarId=calendar_id, body=main_event).execute()
        
        # Создаем напоминания
        start_dt = datetime.datetime.fromisoformat(event_data['start'])
        
        # Напоминание за 1 час
        reminder_1h_start = start_dt - datetime.timedelta(hours=1)
        reminder_1h_event = {
            'summary': f"⏰ НАПОМИНАНИЕ за 1 час: {event_data['summary']}",
            'description': f"Напоминание о предстоящем событии через 1 час:\n\n{event_data['description']}",
            'start': {'dateTime': reminder_1h_start.strftime('%Y-%m-%dT%H:%M:%S'), 'timeZone': 'Europe/Minsk'},
            'end': {'dateTime': (reminder_1h_start + datetime.timedelta(minutes=15)).strftime('%Y-%m-%dT%H:%M:%S'), 'timeZone': 'Europe/Minsk'},
            'reminders': {'useDefault': True},
            'colorId': '11'
        }
        service.events().insert(calendarId=calendar_id, body=reminder_1h_event).execute()
        
        # Напоминание за 1 день
        reminder_1d_start = start_dt - datetime.timedelta(days=1)
        reminder_1d_event = {
            'summary': f"📅 НАПОМИНАНИЕ за 1 день: {event_data['summary']}",
            'description': f"Напоминание о предстоящем событии завтра:\n\n{event_data['description']}",
            'start': {'dateTime': reminder_1d_start.strftime('%Y-%m-%dT%H:%M:%S'), 'timeZone': 'Europe/Minsk'},
            'end': {'dateTime': (reminder_1d_start + datetime.timedelta(minutes=15)).strftime('%Y-%m-%dT%H:%M:%S'), 'timeZone': 'Europe/Minsk'},
            'reminders': {'useDefault': True},
            'colorId': '9'
        }
        service.events().insert(calendarId=calendar_id, body=reminder_1d_event).execute()
        
        return {'api_link': created_event.get('htmlLink'), 'ics_file': None}
        
    except Exception as e:
        print(f"Ошибка календаря: {e}")
        return {'api_link': None, 'ics_file': None}

@bot.message_handler(content_types=['document'])
def handle_document(message):
    """Обработчик для документов"""
    bot.send_chat_action(message.chat.id, 'typing')
    
    file_info = bot.get_file(message.document.file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    
    # Для PDF используем простой подход
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(io.BytesIO(downloaded_file))
        text_content = ""
        for page in reader.pages:
            text_content += page.extract_text() + "\n"
    except:
        bot.send_message(message.chat.id, "❌ Не удалось прочитать PDF. Попробуйте отправить скриншот.")
        return
    
    if len(text_content.strip()) < 50:
        bot.send_message(message.chat.id, "⚠️ Извлечено мало текста из PDF. Попробуйте отправить скриншот.")
        return
    
    bot.send_message(message.chat.id, "🤖 Обрабатываю с помощью ИИ...")
    
    # Отправляем в OpenAI
    reply = ask_openai(text_content)
    
    if reply.startswith("Ошибка"):
        bot.send_message(message.chat.id, f"❌ {reply}")
        return
    
    # Отправляем ответ
    try:
        bot.send_message(message.chat.id, reply, parse_mode='Markdown')
    except:
        bot.send_message(message.chat.id, reply)
    
    # Создаем событие в календаре
    try:
        date_result = smart_date_parsing(reply, text_content)
        
        if not date_result:
            raise Exception("Не найдена дата")
        
        date_str = date_result['date_str']
        time_str = date_result['time_str']
        
        # Парсим дату и время
        if len(date_str.split('.')[-1]) == 2:
            date_obj = datetime.datetime.strptime(date_str, "%d.%m.%y")
        else:
            date_obj = datetime.datetime.strptime(date_str, "%d.%m.%Y")
        
        time_obj = datetime.datetime.strptime(time_str, "%H:%M")
        start_dt = date_obj.replace(hour=time_obj.hour, minute=time_obj.minute)
        end_dt = start_dt + datetime.timedelta(hours=1)
        
        # Извлекаем summary из ответа
        lines = reply.split('\n')
        summary = "Заказ"
        for line in lines:
            if "тип транспортного средства:" in line.lower():
                vehicle = line.split(':')[-1].strip().replace('**', '').replace('*', '')
                summary = f"{vehicle} - Заказ"
                break
        
        event_data = {
            'summary': summary,
            'description': reply.replace('**', '').replace('*', '').strip(),
            'start': start_dt.strftime('%Y-%m-%dT%H:%M:%S'),
            'end': end_dt.strftime('%Y-%m-%dT%H:%M:%S')
        }
        
        result = add_event_to_calendar(event_data)
        
        if result['api_link']:
            bot.send_message(message.chat.id, f'✅ Событие добавлено в Google Календарь!\n{result["api_link"]}')
        else:
            bot.send_message(message.chat.id, '⚠️ Не удалось создать событие в календаре.')
            
    except Exception as e:
        print(f"Ошибка: {e}")
        bot.send_message(message.chat.id, "❌ Не удалось создать событие в календаре.")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    """Обработчик для фотографий"""
    bot.send_chat_action(message.chat.id, 'typing')
    
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    
    bot.send_message(message.chat.id, "🔍 Анализирую фотографию...")
    
    # Извлекаем текст из изображения
    image_text = extract_text_from_image_railway(io.BytesIO(downloaded_file))
    
    if len(image_text.strip()) < 20:
        bot.send_message(message.chat.id, "⚠️ Извлечено мало текста из фотографии.")
        return
    
    bot.send_message(message.chat.id, "🤖 Обрабатываю с помощью ИИ...")
    
    # Отправляем в OpenAI
    reply = ask_openai(image_text)
    
    if reply.startswith("Ошибка"):
        bot.send_message(message.chat.id, f"❌ {reply}")
        return
    
    # Отправляем ответ
    try:
        bot.send_message(message.chat.id, reply, parse_mode='Markdown')
    except:
        bot.send_message(message.chat.id, reply)
    
    # Создаем событие в календаре (аналогично handle_document)
    try:
        date_result = smart_date_parsing(reply, image_text)
        
        if not date_result:
            raise Exception("Не найдена дата")
        
        date_str = date_result['date_str']
        time_str = date_result['time_str']
        
        # Парсим дату и время
        if len(date_str.split('.')[-1]) == 2:
            date_obj = datetime.datetime.strptime(date_str, "%d.%m.%y")
        else:
            date_obj = datetime.datetime.strptime(date_str, "%d.%m.%Y")
        
        time_obj = datetime.datetime.strptime(time_str, "%H:%M")
        start_dt = date_obj.replace(hour=time_obj.hour, minute=time_obj.minute)
        end_dt = start_dt + datetime.timedelta(hours=1)
        
        # Извлекаем summary из ответа
        lines = reply.split('\n')
        summary = "Заказ"
        for line in lines:
            if "тип транспортного средства:" in line.lower():
                vehicle = line.split(':')[-1].strip().replace('**', '').replace('*', '')
                summary = f"{vehicle} - Заказ"
                break
        
        event_data = {
            'summary': summary,
            'description': reply.replace('**', '').replace('*', '').strip(),
            'start': start_dt.strftime('%Y-%m-%dT%H:%M:%S'),
            'end': end_dt.strftime('%Y-%m-%dT%H:%M:%S')
        }
        
        result = add_event_to_calendar(event_data)
        
        if result['api_link']:
            bot.send_message(message.chat.id, f'✅ Событие добавлено в Google Календарь!\n{result["api_link"]}')
        else:
            bot.send_message(message.chat.id, '⚠️ Не удалось создать событие в календаре.')
            
    except Exception as e:
        print(f"Ошибка: {e}")
        bot.send_message(message.chat.id, "❌ Не удалось создать событие в календаре.")

@bot.message_handler(content_types=['text'])
def handle_text(message):
    """Обработчик для текстовых сообщений"""
    bot.send_chat_action(message.chat.id, 'typing')
    
    bot.send_message(message.chat.id, "🤖 Обрабатываю текст...")
    
    # Отправляем в OpenAI
    reply = ask_openai(message.text)
    
    if reply.startswith("Ошибка"):
        bot.send_message(message.chat.id, f"❌ {reply}")
        return
    
    # Отправляем ответ
    try:
        bot.send_message(message.chat.id, reply, parse_mode='Markdown')
    except:
        bot.send_message(message.chat.id, reply)
    
    # Создаем событие в календаре (аналогично handle_document)
    try:
        date_result = smart_date_parsing(reply, message.text)
        
        if not date_result:
            raise Exception("Не найдена дата")
        
        date_str = date_result['date_str']
        time_str = date_result['time_str']
        
        # Парсим дату и время
        if len(date_str.split('.')[-1]) == 2:
            date_obj = datetime.datetime.strptime(date_str, "%d.%m.%y")
        else:
            date_obj = datetime.datetime.strptime(date_str, "%d.%m.%Y")
        
        time_obj = datetime.datetime.strptime(time_str, "%H:%M")
        start_dt = date_obj.replace(hour=time_obj.hour, minute=time_obj.minute)
        end_dt = start_dt + datetime.timedelta(hours=1)
        
        # Извлекаем summary из ответа
        lines = reply.split('\n')
        summary = "Заказ"
        for line in lines:
            if "тип транспортного средства:" in line.lower():
                vehicle = line.split(':')[-1].strip().replace('**', '').replace('*', '')
                summary = f"{vehicle} - Заказ"
                break
        
        event_data = {
            'summary': summary,
            'description': reply.replace('**', '').replace('*', '').strip(),
            'start': start_dt.strftime('%Y-%m-%dT%H:%M:%S'),
            'end': end_dt.strftime('%Y-%m-%dT%H:%M:%S')
        }
        
        result = add_event_to_calendar(event_data)
        
        if result['api_link']:
            bot.send_message(message.chat.id, f'✅ Событие добавлено в Google Календарь!\n{result["api_link"]}')
        else:
            bot.send_message(message.chat.id, '⚠️ Не удалось создать событие в календаре.')
            
    except Exception as e:
        print(f"Ошибка: {e}")
        bot.send_message(message.chat.id, "❌ Не удалось создать событие в календаре.")

if __name__ == "__main__":
    print("🚀 Бот запущен на Railway...")
    bot.polling(none_stop=True) 