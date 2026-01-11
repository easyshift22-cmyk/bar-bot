import telebot
import mysql.connector
from mysql.connector import Error
import time
from telebot import types
import threading
import traceback

# --- НАСТРОЙКИ ---
TOKEN = '8285671558:AAHsrgoANT0OjE4yy1G_frBktvkkdUauT-Y'
PASSWORD_PHRASE = "EasyShift123"

DB_CONFIG = {
    'user': 'easyshift2',
    'password': 'EasyShift123321',
    'host': '77.222.40.251',
    'database': 'easyshift2',
    'port': 3308,
    'charset': 'utf8mb4',
    'use_unicode': True,
    'connect_timeout': 10
}

bot = telebot.TeleBot(TOKEN)
active_sessions = set() 
admin_messages = {} # Храним {order_id: {admin_id: message_id}}

def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)

def send_error_to_admins(error_text):
    """Отправляет текст ошибки всем авторизованным админам"""
    for admin_id in list(active_sessions):
        try:
            bot.send_message(admin_id, f"⚠️ **СИСТЕМНАЯ ОШИБКА:**\n`{error_text}`", parse_mode="Markdown")
        except:
            pass

def sync_status_update(order_id, new_status, cocktail_name, username, comment):
    """Обновляет сообщение у всех админов"""
    status_map = {'new': '🆕 Новый', 'ready': '✅ Готов', 'cancelled': '❌ Отменён'}
    status_text = status_map.get(new_status, new_status)
    
    text = (f"📦 *ЗАКАЗ №{order_id}*\n"
            f"🍹 *Коктейль:* {cocktail_name}\n"
            f"👤 *Клиент:* @{username}\n"
            f"📝 *Коммент:* {comment}\n"
            f"📊 *Статус:* {status_text}")

    if order_id in admin_messages:
        for admin_id, msg_id in admin_messages[order_id].items():
            try:
                bot.edit_message_text(chat_id=admin_id, message_id=msg_id, text=text, reply_markup=None, parse_mode="Markdown")
            except:
                pass

# --- МОНИТОРИНГ ---

def monitor():
    global active_sessions
    print("Мониторинг запущен")
    while True:
        if len(active_sessions) > 0:
            conn = None
            try:
                conn = get_db_connection()
                cursor = conn.cursor(dictionary=True)
                
                query = """
                    SELECT o.order_id, o.status, o.comment, u.tg_username, c.name as c_name 
                    FROM Orders o 
                    LEFT JOIN Users u ON o.user_id = u.user_id 
                    LEFT JOIN Cocktails c ON o.cocktail_id = c.id
                    WHERE o.is_notified = 0
                """
                cursor.execute(query)
                new_orders = cursor.fetchall()

                for order in new_orders:
                    oid = order['order_id']
                    c_name = order['c_name'] or "Неизвестно"
                    uname = order['tg_username'] or "N/A"
                    comm = order['comment'] or "-"
                    
                    text = (f"📦 *ЗАКАЗ №{oid}*\n"
                            f"🍹 *Коктейль:* {c_name}\n"
                            f"👤 *Клиент:* @{uname}\n"
                            f"📝 *Коммент:* {comm}\n"
                            f"📊 *Статус:* 🆕 Новый")
                    
                    markup = types.InlineKeyboardMarkup(row_width=2)
                    markup.add(
                        types.InlineKeyboardButton("✅ Применить", callback_data=f"conf_ready_{oid}"),
                        types.InlineKeyboardButton("❌ Отменить", callback_data=f"conf_cancel_{oid}")
                    )
                    
                    if oid not in admin_messages: admin_messages[oid] = {}

                    for admin_id in list(active_sessions):
                        try:
                            msg = bot.send_message(admin_id, text, reply_markup=markup, parse_mode="Markdown")
                            admin_messages[oid][admin_id] = msg.message_id
                        except: pass

                    cursor.execute("UPDATE Orders SET is_notified = 1 WHERE order_id = %s", (oid,))
                    conn.commit()

                cursor.close()
                conn.close()
            except Exception:
                err = traceback.format_exc()
                print(err)
                send_error_to_admins(err) # Шлем ошибку в ТГ
                if conn: conn.close()
        
        time.sleep(20)

# --- КНОПКИ ---

@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    data = call.data.split('_')
    action, state, oid = data[0], data[1], data[2]

    if action == "conf":
        confirm_markup = types.InlineKeyboardMarkup()
        confirm_markup.add(
            types.InlineKeyboardButton("Да, уверен", callback_data=f"set_{state}_{oid}"),
            types.InlineKeyboardButton("Назад", callback_data=f"back_{oid}")
        )
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=confirm_markup)

    elif action == "set":
        db_status = 'ready' if state == 'ready' else 'cancelled'
        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            # Получаем данные для обновления текста у всех
            cursor.execute("SELECT o.*, u.tg_username, c.name FROM Orders o LEFT JOIN Users u ON o.user_id = u.user_id LEFT JOIN Cocktails c ON o.cocktail_id = c.id WHERE o.order_id = %s", (oid,))
            order = cursor.fetchone()
            
            cursor.execute("UPDATE Orders SET status = %s WHERE order_id = %s", (db_status, oid))
            conn.commit()
            
            sync_status_update(oid, db_status, order['name'], order['tg_username'], order['comment'])
            conn.close()
        except Exception:
            send_error_to_admins(traceback.format_exc())
            if conn: conn.close()

    elif action == "back":
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("✅ Применить", callback_data=f"conf_ready_{oid}"),
            types.InlineKeyboardButton("❌ Отменить", callback_data=f"conf_cancel_{oid}")
        )
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == PASSWORD_PHRASE)
def auth(message):
    global active_sessions
    active_sessions.add(message.chat.id)
    bot.send_message(message.chat.id, "🔓 Доступ разрешен! Ошибки и заказы будут приходить сюда.")

if __name__ == '__main__':
    threading.Thread(target=monitor, daemon=True).start()
    bot.infinity_polling()
