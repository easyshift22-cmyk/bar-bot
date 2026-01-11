import telebot
import mysql.connector
import time
from telebot import types
from mysql.connector import Error

# Настройки бота и базы данных
TOKEN = '8285671558:AAHsrgoANT0OjE4yy1G_frBktvkkdUauT-Y'  # Замени на актуальный токен
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

# Проверка новых заказов
def check_new_orders():
    conn = get_db_connection()
    if not conn:
        return

    try:
        cursor = conn.cursor(dictionary=True)
        # Запрос тянет данные заказа + название коктейля + все ингредиенты
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
            # Формируем список ингредиентов (пропускаем пустые)
            ingredients = []
            for num in range(1, 7):
                ing_name = order.get(f'ing_{num}')
                ing_qty = order.get(f'qty_{num}')
                if ing_name and ing_name.strip():
                    ingredients.append(f"  🔹 {ing_name}: {ing_qty}")
            
            ingredients_text = "\n".join(ingredients) if ingredients else "  Нет данных о составе"

            # Текст сообщения
            msg_text = (
                f"🆕 **НОВЫЙ ЗАКАЗ №{order['order_id']}**\n"
                f"━━━━━━━━━━━━━━\n"
                f"🍸 **Коктейль:** {order['cocktail_name']}\n"
                f"🔢 **Количество:** {order['quantity']}\n"
                f"💬 **Коммент:** {order['comment'] if order['comment'] else '---'}\n"
                f"━━━━━━━━━━━━━━\n"
                f"📜 **СОСТАВ:**\n{ingredients_text}"
            )

            # Клавиатура управления
            markup = types.InlineKeyboardMarkup()
            btn_done = types.InlineKeyboardButton("✅ Готово", callback_data=f"done_{order['order_id']}")
            btn_cancel = types.InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_{order['order_id']}")
            markup.add(btn_done, btn_cancel)

            # Отправка всем активным админам
            for admin_id in active_sessions:
                try:
                    bot.send_message(admin_id, msg_text, reply_markup=markup, parse_mode="Markdown")
                except Exception as e:
                    print(f"Не удалось отправить сообщение {admin_id}: {e}")

            # Помечаем как уведомленный
            cursor.execute("UPDATE Orders SET is_notified = 1 WHERE order_id = %s", (order['order_id'],))
        
        conn.commit()
    except Error as e:
        print(f"Ошибка при работе с БД: {e}")
    finally:
        cursor.close()
        conn.close()

# Обработчик кнопок Готово/Отмена
@bot.callback_query_handler(func=lambda call: call.data.startswith(('done_', 'cancel_')))
def handle_order_action(call):
    action, order_id = call.data.split('_')
    status_text = "✅ Выполнен" if action == "done" else "❌ Отменен"
    
    # Кнопка НАЗАД
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⬅️ Вернуть в список (Назад)", callback_data=f"reset_{order_id}"))

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=call.message.text + f"\n\n**СТАТУС:** {status_text}",
        reply_markup=markup,
        parse_mode="Markdown"
    )

# Обработчик кнопки НАЗАД (возвращает заказ в работу)
@bot.callback_query_handler(func=lambda call: call.data.startswith('reset_'))
def handle_reset_order(call):
    order_id = call.data.split('_')[1]
    
    # Возвращаем исходные кнопки (Готово/Отмена)
    markup = types.InlineKeyboardMarkup()
    btn_done = types.InlineKeyboardButton("✅ Готово", callback_data=f"done_{order_id}")
    btn_cancel = types.InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_{order_id}")
    markup.add(btn_done, btn_cancel)

    # Убираем приписку статуса (просто берем текст до разделителя статуса)
    original_text = call.message.text.split("\n\n**СТАТУС:**")[0]

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=original_text,
        reply_markup=markup,
        parse_mode="Markdown"
    )

# Авторизация
@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id, "Введите пароль для доступа к заказам:")

@bot.message_handler(func=lambda message: message.text == PASSWORD)
def auth(message):
    active_sessions.add(message.chat.id)
    bot.send_message(message.chat.id, "✅ Авторизация успешна! Теперь вы получаете уведомления о заказах.")

# Запуск мониторинга
if __name__ == '__main__':
    print("Бот запущен...")
    import threading

    def run_polling():
        while True:
            try:
                check_new_orders()
                time.sleep(10) # Проверка каждые 10 секунд
            except Exception as e:
                print(f"Ошибка мониторинга: {e}")
                time.sleep(5)

    threading.Thread(target=run_polling, daemon=True).start()
    bot.polling(none_stop=True)
