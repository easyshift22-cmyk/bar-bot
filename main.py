import telebot
import mysql.connector
from mysql.connector import Error
import time
from telebot import types
import threading

# --- НАСТРОЙКИ ---
TOKEN = '8285671558:AAHsrgoANT0OjE4yy1G_frBktvkkdUauT-Y'
PASSWORD_PHRASE = "EasyShift123"

DB_CONFIG = {
    'user': 'easyshift2',
    'password': 'EasyShift123321',
    'host': '77.222.40.251',
    'database': 'easyshift2',
    'charset': 'utf8mb4',
    'port': 3308
}

bot = telebot.TeleBot(TOKEN)
active_sessions = set()

def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)

# --- ЛОГИКА С ФЛАГОМ УВЕДОМЛЕНИЯ ---

def monitor():
    print(f"--- МОНИТОРИНГ ПО ФЛАГУ is_notified ЗАПУЩЕН ---")
    
    while True:
        if active_sessions:
            conn = None
            try:
                conn = get_db_connection()
                cursor = conn.cursor(dictionary=True)
                
                # Ищем только те заказы, которые бот еще не отправлял
                query = """
                    SELECT o.order_id, u.tg_username, c.name as cocktail_name 
                    FROM Orders o 
                    LEFT JOIN Users u ON o.user_id = u.user_id 
                    LEFT JOIN Cocktails c ON o.cocktail_id = c.id
                    WHERE o.is_notified = 0
                    ORDER BY o.order_id ASC
                """
                cursor.execute(query)
                new_orders = cursor.fetchall()

                for order in new_orders:
                    oid = order['order_id']
                    
                    text = (f"🆕 *НОВЫЙ ЗАКАЗ №{oid}*\n"
                            f"🍹 *Коктейль:* {order['cocktail_name']}\n"
                            f"👤 *Клиент:* @{order['tg_username'] or 'N/A'}")
                    
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton("✅ Готово", callback_data=f"done_{oid}"))
                    
                    # Отправляем всем админам
                    sent_success = False
                    for admin_id in active_sessions:
                        try:
                            bot.send_message(admin_id, text, reply_markup=markup, parse_mode="Markdown")
                            sent_success = True
                        except Exception as e:
                            print(f"Ошибка отправки админу {admin_id}: {e}")

                    # Если хоть кому-то отправили, помечаем в базе как "просмотрено"
                    if sent_success:
                        cursor.execute("UPDATE Orders SET is_notified = 1 WHERE order_id = %s", (oid,))
                        conn.commit()
                        print(f"Заказ №{oid} помечен как отправленный.")

                cursor.close()
                conn.close()
            except Exception as e:
                print(f"Ошибка в цикле: {e}")
                if conn: conn.close()
        
        time.sleep(10)

# --- ОБРАБОТЧИКИ (Оставляем как были) ---

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id, "🤖 Бар-система активна. Введите пароль:")

@bot.message_handler(func=lambda m: m.text == PASSWORD_PHRASE)
def auth(message):
    active_sessions.add(message.chat.id)
    bot.send_message(message.chat.id, "🔓 Доступ разрешен!")

@bot.callback_query_handler(func=lambda call: True)
def callback_handle(call):
    action, oid = call.data.split('_')
    # Здесь мы меняем именно статус готовности коктейля
    status = 'ready' if action == 'done' else 'cancelled'
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE Orders SET status = %s WHERE order_id = %s", (status, oid))
        conn.commit()
        cursor.close()
        conn.close()
        bot.edit_message_text(f"Заказ #{oid}: {'✅ Выполнен' if action == 'done' else '❌ Отменен'}", 
                              call.message.chat.id, call.message.message_id)
    except Exception as e:
        print(f"Ошибка callback: {e}")

if __name__ == '__main__':
    threading.Thread(target=monitor, daemon=True).start()
    bot.infinity_polling()
