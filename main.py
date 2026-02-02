import telebot
import mysql.connector
import time
import threading
from telebot import types
from mysql.connector import Error

# --- НАСТРОЙКИ ---
TOKEN = '8112243924:AAGv-nqJx-ld1oKm8fEQGk0-1J9eWs0A0Nk' 
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
active_sessions = set()

def get_db_connection():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except Error as e:
        print(f"Ошибка подключения к БД: {e}")
        return None

# --- ФУНКЦИЯ СОЗДАНИЯ КЛАВИАТУРЫ ---
def get_order_markup(order_id, status='new'):
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    if status == 'new':
        btn_cook = types.InlineKeyboardButton("👨‍🍳 В процессе", callback_data=f"cook_{order_id}")
        btn_done = types.InlineKeyboardButton("✅ Готово", callback_data=f"done_{order_id}")
        btn_cancel = types.InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_{order_id}")
        markup.add(btn_cook, btn_done, btn_cancel)
    elif status == 'cooking':
        btn_done = types.InlineKeyboardButton("✅ Готово", callback_data=f"done_{order_id}")
        btn_cancel = types.InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_{order_id}")
        markup.add(btn_done, btn_cancel)
    else: # ready или cancelled
        btn_reset = types.InlineKeyboardButton("⬅️ Вернуть в список", callback_data=f"reset_{order_id}")
        markup.add(btn_reset)
    
    # Кнопка комментария доступна для активных заказов
    if status in ['new', 'cooking']:
        btn_comment = types.InlineKeyboardButton("💬 Коммент бармена", callback_data=f"comment_{order_id}")
        markup.add(btn_comment)

    btn_refresh = types.InlineKeyboardButton("🔄 Обновить статус", callback_data=f"refresh_{order_id}")
    markup.add(btn_refresh)
    return markup

# --- ЛОГИКА МОНИТОРИНГА НОВЫХ ЗАКАЗОВ ---
def check_new_orders():
    conn = get_db_connection()
    if not conn:
        return
    try:
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT o.order_id, c.name as cocktail_name, o.quantity, o.comment, o.BarmanComment,
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
            ingredients = []
            for num in range(1, 7):
                name = order.get(f'ing_{num}')
                qty = order.get(f'qty_{num}')
                if name and name.strip():
                    ingredients.append(f"  🔹 {name}: {qty}")
            
            ing_text = "\n".join(ingredients) if ingredients else "  Состав не указан"
            b_comment = f"\n📝 **Бармен:** {order['BarmanComment']}" if order['BarmanComment'] else ""

            msg_text = (
                f"🆕 НОВЫЙ ЗАКАЗ №{order['order_id']}\n"
                f"━━━━━━━━━━━━━━\n"
                f"🍸 Коктейль: {order['cocktail_name']}\n"
                f"🔢 Количество: {order['quantity']}\n"
                f"💬 Клиент: {order['comment'] if order['comment'] else '---'}"
                f"{b_comment}\n"
                f"━━━━━━━━━━━━━━\n"
                f"📜 СОСТАВ:\n{ing_text}"
            )

            markup = get_order_markup(order['order_id'], 'new')
            for admin_id in list(active_sessions):
                try:
                    bot.send_message(admin_id, msg_text, reply_markup=markup, parse_mode="Markdown")
                except:
                    pass
            cursor.execute("UPDATE Orders SET is_notified = 1 WHERE order_id = %s", (order['order_id'],))
        conn.commit()
    except Error as e:
        print(f"Ошибка мониторинга: {e}")
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()

# --- ОБРАБОТЧИК КНОПКИ "ДОБАВИТЬ КОММЕНТАРИЙ" ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('comment_'))
def handle_add_comment(call):
    order_id = call.data.split('_')[1]
    msg = bot.send_message(call.message.chat.id, f"📝 Введите комментарий для заказа №{order_id}:")
    # Регистрируем следующий шаг: бот будет ждать текст
    bot.register_next_step_handler(msg, process_barman_comment, order_id, call.message.message_id)
    bot.answer_callback_query(call.id)

def process_barman_comment(message, order_id, original_msg_id):
    comment_text = message.text
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            query = "UPDATE Orders SET BarmanComment = %s WHERE order_id = %s"
            cursor.execute(query, (comment_text, order_id))
            conn.commit()
            bot.reply_to(message, f"✅ Комментарий к заказу №{order_id} сохранен!")
            
            # Предлагаем пользователю обновить статус сообщения, чтобы увидеть изменения
            bot.send_message(message.chat.id, "Нажмите кнопку '🔄 Обновить статус' на заказе, чтобы отобразить комментарий.")
        except Error as e:
            bot.reply_to(message, "❌ Ошибка при сохранении в базу.")
            print(f"Ошибка БД: {e}")
        finally:
            conn.close()

# --- ОБРАБОТЧИКИ КНОПОК ДЕЙСТВИЯ ---
@bot.callback_query_handler(func=lambda call: call.data.startswith(('done_', 'cancel_', 'cook_')))
def handle_order_action(call):
    data = call.data.split('_')
    action, order_id = data[0], data[1]
    user_name = call.from_user.first_name + (f" {call.from_user.last_name}" if call.from_user.last_name else "")
    
    status_map = {'done': ('ready', '✅ Выполнен'), 'cancel': ('cancelled', '❌ Отменен'), 'cook': ('cooking', '👨‍🍳 В процессе')}
    db_status, display_status = status_map[action]
    
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            query = "UPDATE Orders SET status = %s, worker_name = %s WHERE order_id = %s"
            cursor.execute(query, (db_status, user_name, order_id))
            conn.commit()
        finally:
            conn.close()

    status_line = f"\n\nСтатус: {display_status} ({user_name})"
    clean_text = call.message.text.split("\n\nСтатус:")[0]
    markup = get_order_markup(order_id, db_status)
    
    try:
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                              text=clean_text + status_line, reply_markup=markup)
    except:
        bot.answer_callback_query(call.id, "Статус обновлен!")

# --- КНОПКА "ОБНОВИТЬ" ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('refresh_'))
def handle_refresh(call):
    order_id = call.data.split('_')[1]
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT status, worker_name, BarmanComment FROM Orders WHERE order_id = %s", (order_id,))
            order_data = cursor.fetchone()
            
            if order_data:
                labels = {'new': '🆕 Ожидает', 'cooking': '👨‍🍳 В процессе', 'ready': '✅ Выполнен', 'cancelled': '❌ Отменен'}
                cur_status = labels.get(order_data['status'], order_data['status'])
                worker = order_data['worker_name'] or "Никто"
                
                # Добавляем комментарий бармена в текст при обновлении, если он есть
                b_comment = f"\n📝 **Бармен:** {order_data['BarmanComment']}" if order_data['BarmanComment'] else ""
                
                # Собираем заново основной текст (до раздела Статус)
                main_part = call.message.text.split("\n\nСтатус:")[0]
                # Убираем старый комментарий бармена из текста, если он там был, чтобы не дублировать
                if "📝 Бармен:" in main_part:
                    main_part = main_part.split("\n📝 Бармен:")[0]

                new_text = main_part + b_comment + f"\n\nСтатус: {cur_status} ({worker})"
                markup = get_order_markup(order_id, order_data['status'])
                
                bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                                      text=new_text, reply_markup=markup, parse_mode="Markdown")
                bot.answer_callback_query(call.id, "Данные обновлены!")
        finally:
            conn.close()

# --- КНОПКА "НАЗАД" ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('reset_'))
def handle_reset_order(call):
    order_id = call.data.split('_')[1]
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE Orders SET status = 'new', worker_name = NULL WHERE order_id = %s", (order_id,))
            conn.commit()
        finally:
            conn.close()

    clean_text = call.message.text.split("\n\nСтатус:")[0]
    markup = get_order_markup(order_id, 'new')
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                          text=clean_text, reply_markup=markup, parse_mode="Markdown")

# --- АВТОРИЗАЦИЯ И ЗАПУСК ---
@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id, "👋 Привет! Введите пароль:")

@bot.message_handler(func=lambda message: message.text == PASSWORD)
def auth(message):
    active_sessions.add(message.chat.id)
    bot.send_message(message.chat.id, "🔓 Доступ открыт! Ожидайте заказы.")

def run_db_monitor():
    while True:
        check_new_orders()
        time.sleep(5)

if __name__ == '__main__':
    print("Бот запущен...")
    threading.Thread(target=run_db_monitor, daemon=True).start()
    bot.polling(none_stop=True)
