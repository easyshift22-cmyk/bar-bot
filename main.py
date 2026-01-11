import telebot
import mysql.connector
import time
import threading
from telebot import types
from mysql.connector import Error

# --- НАСТРОЙКИ ---
TOKEN = '8285671558:AAHsrgoANT0OjE4yy1G_frBktvkkdUauT-Y' 
bot = telebot.TeleBot(TOKEN)

DB_CONFIG = {
    'user': 'easyshift2',
    'password': 'EasyShift123321',
    'host': '77.222.40.251',
    'database': 'easyshift2',
    'port': 3308,
    'charset': 'utf8mb4',
    'collation': 'utf8mb4_unicode_ci',
    'use_unicode': True
}

PASSWORD = "EasyShift123"
active_sessions = set() # Список ID админов в памяти

def get_db_connection():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except Error as e:
        print(f"Ошибка подключения к БД: {e}")
        return None

# --- ЛОГИКА МОНИТОРИНГА ЗАКАЗОВ ---
def check_new_orders():
    conn = get_db_connection()
    if not conn:
        return

    try:
        cursor = conn.cursor(dictionary=True)
        # Тянем заказ, имя коктейля и все ингредиенты
        query = """
            SELECT o.order_id, c.name as cocktail_name, o.quantity, o.comment,
                   i.ing_1, i.qty_1, i.ing_2, i.qty_2, i.ing_3, i.qty_3,
                   i.ing_4, i.qty_4, i.ing_5, i.qty_5, i.ing_6, i.qty_6
            FROM Orders o
            JOIN Cocktails c ON o.cocktail_id = c.id
            LEFT JOIN Ingredients i ON c.id = i.cocktail_id
            WHERE o.is_notified = 0
        """
        cursor.execute(query)
        new_orders = cursor.fetchall()

        for order in new_orders:
            # Сборка состава
            ingredients = []
            for num in range(1, 7):
                name = order.get(f'ing_{num}')
                qty = order.get(f'qty_{num}')
                if name and name.strip():
                    ingredients.append(f"  🔹 {name}: {qty}")
            
            ing_text = "\n".join(ingredients) if ingredients else "  Состав не указан"

            # Текст уведомления
            msg_text = (
                f"🆕 НОВЫЙ ЗАКАЗ №{order['order_id']}\n"
                f"━━━━━━━━━━━━━━\n"
                f"🍸 Коктейль: {order['cocktail_name']}\n"
                f"🔢 Количество: {order['quantity']}\n"
                f"💬 Коммент: {order['comment'] if order['comment'] else '---'}\n"
                f"━━━━━━━━━━━━━━\n"
                f"📜 СОСТАВ:\n{ing_text}"
            )

            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton("✅ Готово", callback_data=f"done_{order['order_id']}"),
                types.InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_{order['order_id']}")
            )

            # Рассылка всем авторизованным
            for admin_id in list(active_sessions):
                try:
                    bot.send_message(admin_id, msg_text, reply_markup=markup)
                except:
                    pass

            # Помечаем в базе, что уведомление отправлено
            cursor.execute("UPDATE Orders SET is_notified = 1 WHERE order_id = %s", (order['order_id'],))
        
        conn.commit()
    except Error as e:
        print(f"Ошибка мониторинга: {e}")
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()

# --- ОБРАБОТЧИКИ КНОПОК ---

@bot.callback_query_handler(func=lambda call: call.data.startswith(('done_', 'cancel_')))
def handle_order_action(call):
    action, order_id = call.data.split('_')
    
    # Имя админа
    user_name = call.from_user.first_name + (f" {call.from_user.last_name}" if call.from_user.last_name else "")
    
    db_status = 'ready' if action == 'done' else 'cancelled'
    status_display = "✅ Выполнен" if action == "done" else "❌ Отменен"
    status_line = f"\n\nСтатус: {status_display} ({user_name})"
    
    # Обновляем БД
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE Orders SET status = %s WHERE order_id = %s", (db_status, order_id))
            conn.commit()
        finally:
            conn.close()

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⬅️ Вернуть в список (Назад)", callback_data=f"reset_{order_id}"))

    # Редактируем сообщение (без parse_mode во избежание ошибок спецсимволов)
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=call.message.text + status_line,
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('reset_'))
def handle_reset_order(call):
    order_id = call.data.split('_')[1]
    
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE Orders SET status = 'new' WHERE order_id = %s", (order_id,))
            conn.commit()
        finally:
            conn.close()

    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ Готово", callback_data=f"done_{order_id}"),
        types.InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_{order_id}")
    )

    # Убираем приписку статуса
    original_text = call.message.text.split("\n\nСтатус:")[0]

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=original_text,
        reply_markup=markup
    )

# --- АВТОРИЗАЦИЯ ---

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id, "👋 Привет! Введите пароль для доступа к заказам:")

@bot.message_handler(func=lambda message: message.text == PASSWORD)
def auth(message):
    active_sessions.add(message.chat.id)
    bot.send_message(message.chat.id, "🔓 Доступ разрешен! Теперь вы будете получать новые заказы.")

# --- ЗАПУСК ---

def run_db_monitor():
    while True:
        check_new_orders()
        time.sleep(5) # Проверка каждые 5 секунд

if __name__ == '__main__':
    print("Бот успешно запущен и мониторит базу...")
    # Запускаем мониторинг в отдельном потоке
    threading.Thread(target=run_db_monitor, daemon=True).start()
    # Запускаем самого бота
    bot.polling(none_stop=True)
