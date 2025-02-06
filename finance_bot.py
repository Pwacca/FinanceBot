import os
import telebot
from oauth2client.service_account import ServiceAccountCredentials
import gspread
from datetime import datetime
from telebot import types
import time
import platform
import logging
from forex_python.converter import CurrencyRates
import requests
import re

logging.basicConfig(
    filename='bot_errors.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
    
#определение авторизованных пользователей
#------------------------------------------------------------------------------------------------------------------------------------------
UNAUTHORIZED_USERS_FILE = 'unauthorized_users.txt' #файл с никами, у кого есть досутп к боту
AUTHORIZED_USERS_FILE = 'authorized_users.txt' #файл с никами, у кого нет досутпа к боту

def manage_user(file_path, username=None, remove=False):
    try:
        users = set()
        if os.path.exists(file_path):
            with open(file_path, 'r') as file:
                users = {line.strip() for line in file}
                
        if remove and username:
            users.discard(username)
        elif username:
            users.add(username)
            
        with open(file_path, 'w') as file:
            file.write("\n".join(users) + "\n")
            
        return users
    except (IOError, OSError) as e:
        logging.error(f"⚠️ Ошибка работы с файлом {file_path}: {e}")
        return set()

# Загрузка списков пользователей через manage_user
authorized_users = manage_user(AUTHORIZED_USERS_FILE)
unauthorized_users = manage_user(UNAUTHORIZED_USERS_FILE)

#Запуск бота
#------------------------------------------------------------------------------------------------------------------------------------------
# Определяем путь к токену в зависимости от операционной системы
TOKEN_PATHS = {
    "Darwin": "/Users/pwacca/pwacca_expeses_bot_token_for_tests.txt",
    "Linux": "/home/pwacca/pwacca_expeses_bot_token_main.txt"
}
token_file_path = TOKEN_PATHS.get(platform.system())

if not token_file_path:
    raise ValueError("Неподдерживаемая операционная система")
    
with open(token_file_path, 'r') as file:
    BOT_TOKEN = file.read().strip()

bot = telebot.TeleBot(BOT_TOKEN) # Инициализация бота
bot.remove_webhook() # Удаление существующего webhook


#Google Sheets
#-------------------------------------------------------------------------------------------------------------------------------------------

try:
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("crypto-reality-348518-2e061a0ac6ec.json", scope)
    client = gspread.authorize(creds)
    spreadsheet = client.open("Бюджет Катя/Лука")
    expenses_sheet = spreadsheet.worksheet("expenses new")
    budget_sheet = spreadsheet.worksheet("P&L new")
except Exception as e:
    logging.error("Error initializing Google Sheets connection: %s", str(e))


# Списки категорий
#-------------------------------------------------------------------------------------------------------------------------------------------
needs_categories = [
    "Продукты", "Терапия", "Здоровье", "Косметика", "Псина", "Расходники для дома", 
    "Аренда", "Языки", "Спорт", "Моб. интернет", "Дом интернет", "Налоги", "Комуналка",   
]

wants_categories = [
    "Рестики/бары/доставка", "Чай/кофе", "Аксессуары для дома", "Хобби",
    "Подписки", "Такси", "Одежда", "Отпуск", "Подарки", "Путешествия",
]

income_categories = [
    "СКМС", "Шалаш", "Батон", "Аренда Лука", "Аренда Катя", "Прочие Доходы Лука", "Прочие Доходы Катя"
]

currencies = ["Динары", "Драмы", "Рубли", "Доллары", "Евро"
]

#-------------------------------------------------------------------------------------------------------------------------------------------
# Хранение данных пользователя
user_data = {}

def convert_to_euro(amount, currency_name):
    """
    Конвертирует сумму из указанной валюты в евро.
    """
    currency_map = {
        "Динары": "RSD",
        "Драмы": "AMD",
        "Рубли": "RUB",
        "Доллары": "USD",
        "Евро": "EUR"
    }
    currency_code = currency_map.get(currency_name, currency_name)  # Если "Другая Валюта", то вводим код вручную
    
    if currency_code == "EUR":
        return amount
    url = 'https://api.exchangerate-api.com/v4/latest/EUR'
    try:
        rates = requests.get(url).json().get('rates', {})
        if currency_code not in rates:
            raise ValueError(f"Обменный курс для валюты '{currency_name}' недоступен.")
        return round(amount / rates[currency_code], 2)
    except requests.exceptions.RequestException:
        raise ValueError("Ошибка при запросе к API.")

def generate_markup(button_options, include_reset_button=True):
    """
    Создание клавиатуры с опциями.
    """
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for option in button_options:
        markup.add(types.KeyboardButton(option))
    if include_reset_button:
        markup.add(types.KeyboardButton("Вернуться на главную"))
    return markup

def handle_expense_income_input(chat_id, text, user_data, type):
    """
    Обработка ввода категории, суммы и валюты.
    """
    if text in needs_categories + wants_categories + income_categories + ["Прочее"]:
        user_data[chat_id]["category"] = text
        return "Сумма:", types.ReplyKeyboardRemove()
    else:
        try:
            amount = float(text)
            user_data[chat_id]["amount"] = amount
            return "Валюта:", generate_markup(currencies)
        except ValueError:
            return "Нужны цифры", None

def send_message_with_markup(chat_id, text, options, include_reset=True):
    bot.send_message(chat_id, text=text, reply_markup=generate_markup(options, include_reset_button=include_reset))
    
def handle_currency_input(chat_id, text, user_data, context_type, message):
    """
    Обработка ввода валюты и комментария.
    """
    if text in currencies:
        user_data[chat_id]["currency"] = text
        if user_data[chat_id]["category"] == "Прочее":
            bot.send_message(chat_id, text="Комментарий к расходу:", reply_markup=types.ReplyKeyboardRemove())
        else:
            markup = generate_markup(["Пропустить"])
            send_message_with_markup(chat_id, "Комментарий? Можно пропустить:", ["Пропустить"])
    else:
        bot.send_message(chat_id, text="Нет такой валюты")

def save_and_respond_expense_income(chat_id, text, message, context_type):
    """
    Сохранение расхода и отправка ответа пользователю.
    """
    if context_type == "expense" and user_data[chat_id]["category"] == "Прочее" and text == "Пропустить":
        bot.send_message(chat_id, text="Комментарий обязателен для категории 'Прочее'")
    else:
        user_data[chat_id]["comment"] = text if text != "Пропустить" else ""
        if context_type == "expense":
            response = save_expense_income(chat_id, user_data, message, "expense")
        elif context_type == "income":
            response = save_expense_income(chat_id, user_data, message, "income")
        bot.send_message(chat_id, text=response)
        reset_to_main_menu(chat_id)
        
def save_expense_income(chat_id, user_data, message, context_type):
    """
    Сохранение данных расходов или доходов, а также расчет процента выполнения плана.
    """
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        user_name = message.from_user.first_name
        category = user_data[chat_id].get("category", "прочее")
        amount = user_data[chat_id]["amount"]
        currency = user_data[chat_id]["currency"]
        comment = user_data[chat_id].get("comment", "")
        euro_value = convert_to_euro(amount, currency)
        
        # Определение текущей даты для поиска в "P&L new"
        current_month_str = datetime.now().strftime("01.%m.%Y")

        current_month = datetime.now().month   #Получаем номер текущего месяца
        row = [timestamp, user_name, category, amount, currency, euro_value, comment, current_month]
        
        # Добавление данных в таблицу расходов
        for attempt in range(3):  # Три попытки записи
            try:
                expenses_sheet.append_row(row, value_input_option='USER_ENTERED')
                break
            except gspread.exceptions.APIError as api_error:
                logging.warning(f"Google Sheets API error: {api_error}, retrying...")
                time.sleep(2)
        else:
            raise gspread.exceptions.APIError("Не удалось записать в Google Sheets после 3 попыток.")
            
        # Поиск данных о бюджете
        plan_data = get_budget_data(category)
        
        # Если удалось найти план и факт, добавить их в ответ
        if plan_data and context_type == 'expense':
            fact, plan = plan_data
            if plan > 0:
                percent_used = round((fact / plan) * 100, 2)
            else:
                percent_used = 0
                
            # Проверяем, превышен ли бюджет
            if fact > plan:
                response_message = (
                    f"⚠️ БЮДЖЕТ ПРЕВЫШЕН!\n"
                    f"Категория: {category}\n"
                    f"Израсходовано: {int(fact)} из {int(plan)} EUR ({percent_used}%)\n"
                    f"Превышение: {int(fact - plan)} EUR"
                )
            else:
                response_message = (
                    f"{category}:\n\n"
                    f"Осталось {int(plan - fact)} из {int(plan)} EUR ({percent_used}%)"
                )
        elif context_type == 'income':
            response_message = "Доход сохранен"
        else:
            response_message = (
                "Расход сохранен\n\n"
                "⚠️ Не получилось найти данные о бюджете"
            )
            
            
        bot.send_message(chat_id, response_message)
        
        # Возвращение в главное меню
        handle_main_menu(chat_id)
        
    except gspread.exceptions.APIError as api_error:
        logging.error("Google Sheets API error: %s", str(api_error))
        bot.send_message(chat_id, "⚠️ Ошибка соединения с Google Sheets. Попробуйте позже.")
    except Exception as e:
        logging.error("Unexpected error while saving expense/income: %s", str(e))
        bot.send_message(chat_id, "⚠️ Произошла непредвиденная ошибка.")

def get_budget_data(category):
    """
    Получает данные о бюджете (факт и план) для данной категории и текущего месяца.

    :param category: Название категории
    :return: Кортеж (факт, план) или None, если данные не найдены
    """
    try:
        # Автоматически получаем текущую дату в нужном формате "MM.YY"
        current_month_formatted = datetime.now().strftime("%m.%y")
        
        # Получение всех данных с листа "P&L new"
        budget_data = budget_sheet.get_all_values()
        
        # Найти строку с нужной категорией (по колонке C)
        category_row = None
        for i, row in enumerate(budget_data):
            if row[2].strip().lower() == category.lower():  # Колонка C = индекс 2
                category_row = i
                break
        if category_row is None:
            return None  # Категория не найдена
        # Найти колонку с текущим месяцем (по строке 1)
        month_col = None
        for j, cell in enumerate(budget_data[0]):  # Перебираем заголовки (первая строка)
            if cell.strip() == current_month_formatted:  # Сравниваем с "MM.YY"
                month_col = j
                break
        if month_col is None:
            return None  # Дата не найдена
    
        # Получить факт и план (факт в найденной колонке, план - в колонке справа)
        fact_raw = budget_data[category_row][month_col] if budget_data[category_row][month_col] else "0"
        plan_raw = budget_data[category_row][month_col + 1] if budget_data[category_row][month_col + 1] else "0"
    
        fact = float(re.sub(r"\s+", "", fact_raw).replace(",", ".")) if fact_raw else 0
        plan = float(re.sub(r"\s+", "", plan_raw).replace(",", ".")) if plan_raw else 0
    
        return fact, plan  # Вернуть найденные данные

    except Exception as e:
        logging.error(f"⚠️ Ошибка при получении данных о бюджете: {e}")
        return None
    
def start(message):
    """
    Обработка команды /start, приветствие пользователя.
    """
#   markup = generate_markup(["Добавить расход", "Добавить приход"], include_reset_button=False)
    markup = generate_markup(["Добавить расход", "Добавить приход", "Технические операции"], include_reset_button=False)
    bot.send_message(message.chat.id, text="Привет, {0.first_name}!".format(message.from_user), reply_markup=markup)

@bot.message_handler(content_types=['text'])

def handle_text(message):
    """
    Обработка текстовых сообщений от пользователя.
    """
    chat_id = message.chat.id
    username = message.from_user.username
    
    if not handle_authorization(chat_id, username):
        return
    
    text = message.text
    
    if text == "Вернуться на главную":
        handle_main_menu(chat_id)
    elif text == "Добавить расход":
        start_add_expense(chat_id, username)
    elif text == "Добавить приход":
        start_add_income(chat_id, username)
    elif text == "Технические операции":
        handle_technical_operations(chat_id, text, message)
    elif text == "Общая сводка":
        handle_category_summary(chat_id, text)
    else:
        handle_contextual_input(chat_id, text, message)

def handle_authorization(chat_id, username):
    """
    Проверка авторизации пользователя.
    """
    if username in authorized_users:
        return True
    
    if username not in unauthorized_users:
        unauthorized_users.add(username)
        save_user(UNAUTHORIZED_USERS_FILE, username)
        user_data[chat_id] = {'username': username}
        bot.send_message(chat_id, "Вы не авторизованы для использования этого бота. Запрос на авторизацию отправлен владельцу.")
        notify_admin_for_authorization(username)
        
    return False

def notify_admin_for_authorization(username):
    """
    Уведомление администратора о запросе на авторизацию.
    """
    ADMIN_CHAT_ID = 64003764
    markup = types.InlineKeyboardMarkup()
    authorize_button = types.InlineKeyboardButton(text="Авторизовать пользователя", callback_data=f"authorize_{username}")
    ignore_button = types.InlineKeyboardButton(text="Игнорировать", callback_data=f"ignore_{username}")
    markup.add(authorize_button, ignore_button)
    bot.send_message(ADMIN_CHAT_ID, f"Неавторизованный пользователь: @{username} пытался получить доступ к боту.", reply_markup=markup)

def handle_main_menu(chat_id):
    """
    Главное меню бота.
    """
    user_data.pop(chat_id, None)
    markup = generate_markup(["Добавить расход", "Добавить приход", "Технические операции"], include_reset_button=False)
    bot.send_message(chat_id, text="Что дальше?", reply_markup=markup)

def handle_technical_operations(chat_id, text, message):
    """
    Обработка нажатия на кнопку 'Технические операции'.
    """
    if text == "Технические операции":
        markup = generate_markup(["Общая сводка"])
        bot.send_message(chat_id, "Выберите действие:", reply_markup=markup)

def handle_category_summary(chat_id, text):
    """
    Получает и отправляет пользователю общую сводку расходов.
    """
    if text == "Общая сводка":
        try:
            summary_text = get_overall_budget_summary()
            bot.send_message(chat_id, summary_text)
        except Exception as e:
            logging.error(f"⚠️ Ошибка при получении общей сводки: {e}")
            bot.send_message(chat_id, "⚠️ Ошибка при получении данных. Попробуйте позже.")

def get_overall_budget_summary():
    """
    Получает данные бюджета и формирует текст с тремя отдельными секциями:
    1. Суммарные доходы
    2. Needs (Обязательные расходы)
    3. Wants (Желаемые траты)
    """
    try:
        budget_data = budget_sheet.get_all_values()
        
        # Автоматически получаем текущий месяц в формате "MM.YY"
        current_month_str = datetime.now().strftime("%m.%y")
        
        # Определяем индекс колонки с текущим месяцем
        month_col = None
        for j, cell in enumerate(budget_data[0]):  # Перебираем заголовки (первая строка)
            if cell.strip() == current_month_str:
                month_col = j
                break
        
        if month_col is None:
            return "⚠️ Данные за текущий месяц не найдены."
        
        # Суммарные показатели доходов
        total_income_fact = 0
        total_income_plan = 0
        
        # Словари для хранения категорий расходов
        needs_summary = {}
        wants_summary = {}
        
        # Проходим по строкам бюджета
        for i, row in enumerate(budget_data[1:]):  # Пропускаем заголовок (i - индекс строки)
            if len(row) <= month_col + 1:  # Проверяем, достаточно ли колонок
                continue  # Пропускаем строки с недостаточным числом колонок
    
            category = row[2].strip() if len(row) > 2 else ""
    
            # Пропускаем пустые категории
            if not category:
                continue
    
            try:
                fact_raw = row[month_col] if row[month_col] else "0"
                plan_raw = row[month_col + 1] if row[month_col + 1] else "0"
                
                # Очищаем числа от пробелов и заменяем запятые на точки
                fact = float(re.sub(r"\s+", "", fact_raw).replace(",", ".")) if fact_raw else 0
                plan = float(re.sub(r"\s+", "", plan_raw).replace(",", ".")) if plan_raw else 0
                
                if category in income_categories:
                    # Считаем общий доход
                    total_income_fact += fact
                    total_income_plan += plan
                else:
                    # Рассчитываем остаток для расходов
                    remaining = int(plan) - int(fact)
                    print(f"Категория: {category}, Факт: {fact}, План: {plan}, 90%: {plan * 0.9}, 105%: {plan * 1.05}")
                    # Формируем строку с дополнительными знаками в зависимости от ситуации
                    if fact == 0:
                        formatted_text = f"{category}: {int(plan)} EUR"
                    elif fact > 0 and fact < plan * 0.9:  # Меньше 90% от плана – без знака
                        formatted_text = f"{category}: {int(remaining)} из {int(plan)} EUR"
                    elif plan * 0.9 <= fact <= plan * 1.05:  # От 90% до 105% от плана – ⚠️
                        formatted_text = f"{category}: {int(remaining)} из {int(plan)} EUR ⚠️"
                    elif fact > plan * 1.1:  # Больше 110% от плана – ❌
                        formatted_text = f"{category}: {-int(remaining)} EUR ❌"
                    else:  # Между 105% и 110% (неявное превышение) – без знака
                        formatted_text = f"{category}: {-int(remaining)} EUR"
                        
                    # Сортируем по категориям
                    if category in needs_categories:
                        needs_summary[category] = formatted_text
                    elif category in wants_categories:
                        wants_summary[category] = formatted_text
                        
            except ValueError as ve:
                logging.error(f"⚠️ Ошибка преобразования данных в строке {i + 1}: {ve}")
                continue  # Игнорируем ошибочную строку
    
        # Формируем итоговый текст, соблюдая порядок категорий
        summary_text = ""
    
        # Добавляем суммарные доходы
        summary_text += f"💰 Доходы: {int(total_income_fact)} из {int(total_income_plan)} EUR\n"
    
        if needs_summary:
            summary_text += "\n🏠 Needs:\n"
            for category in needs_categories:
                if category in needs_summary:
                    summary_text += f"{needs_summary[category]}\n"
                    
        if wants_summary:
            summary_text += "\n🎉 Wants:\n"
            for category in wants_categories:
                if category in wants_summary:
                    summary_text += f"{wants_summary[category]}\n"
                    
        return summary_text if summary_text else "⚠️ Данные бюджета недоступны."

    except Exception as e:
        logging.error(f"⚠️ Ошибка при обработке данных бюджета: {e}")
        return "⚠️ Ошибка при обработке данных бюджета."

def start_add_expense(chat_id, username):
    """
    Начало процесса добавления расхода.
    """
#   user_data[chat_id] = {"context": "add_expense", "username": username, "date": datetime.now()}
    user_data[chat_id] = {"context": "add_expense", "username": username}
    markup = generate_markup(["Needs", "Wants", "Прочее"])
    bot.send_message(chat_id, text="Тип расхода:", reply_markup=markup)
    
def start_add_income(chat_id, username):
    """
    Начало процесса добавления дохода.
    """
#   user_data[chat_id] = {"context": "add_income", "username": username, "date": datetime.now()}
    user_data[chat_id] = {"context": "add_income", "username": username}
    markup = generate_markup(income_categories)
    bot.send_message(chat_id, text="Тип дохода:", reply_markup=markup)

def handle_contextual_input(chat_id, text, message):
    """
    Обработка контекстного ввода на основании текущего состояния пользователя.
    """
    if text == "Вернуться на главную":
        handle_main_menu(chat_id)
        return

    context = user_data.get(chat_id, {}).get("context")

    if context == "add_expense":
        handle_transaction(chat_id, text, message, "expense")
    elif context == "add_income":
        handle_transaction(chat_id, text, message, "income")
    elif context == "category_summary":
        handle_category_summary(chat_id, text)
    elif context == "technical_operations":
        handle_technical_operations(chat_id, text, message)

def handle_transaction(chat_id, text, message, context_type):
    """
    Обработка ввода для расходов и доходов.
    """
    categories = needs_categories + wants_categories + income_categories + ["Прочее"]
    
    if text in ["Needs", "Wants"] and context_type == "expense":
        user_data[chat_id]["type"] = text
        category_list = needs_categories if text == "Needs" else wants_categories
        bot.send_message(chat_id, text="Категория:", reply_markup=generate_markup(category_list, include_reset_button=True))
        return
    
    if "category" not in user_data[chat_id]:
        user_data[chat_id]["category"] = text
        bot.send_message(chat_id, text="Сумма:", reply_markup=types.ReplyKeyboardRemove())
        return
    
    if "amount" not in user_data[chat_id]:
        try:
            user_data[chat_id]["amount"] = float(text)  # Convert amount to float
            bot.send_message(chat_id, text="Валюта:", reply_markup=generate_markup(currencies))
        except ValueError:
            bot.send_message(chat_id, text="Введите корректную сумму (только числа).")
        return
    
    if "currency" not in user_data[chat_id]:
        if text in currencies:
            user_data[chat_id]["currency"] = text
            markup = generate_markup(["Пропустить"])
            bot.send_message(chat_id, text="Введите комментарий или нажмите 'Пропустить':", reply_markup=markup)
        else:
            bot.send_message(chat_id, text="Нет такой валюты, выберите из списка.")
        return
    
    if "comment" not in user_data[chat_id]:
        user_data[chat_id]["comment"] = text if text != "Пропустить" else ""
        save_and_respond_expense_income(chat_id, text, message, context_type)
        
    save_and_respond_expense_income(chat_id, text, message, context_type)
        
def reset_to_main_menu(chat_id):
    """
    Сброс данных пользователя и возврат к главному меню.
    """
    user_data.pop(chat_id, None)
    markup = generate_markup(["Добавить расход", "Добавить приход", "Технические операции"])
    bot.send_message(chat_id, text="Что дальше?", reply_markup=markup)

@bot.message_handler(commands=['start'])
def start(message):
    """
    Обработка команды /start, приветствие пользователя.
    """
    markup = generate_markup(["Добавить расход", "Добавить приход", "Технические операции"], include_reset_button=False)
    bot.send_message(message.chat.id, text=f"Привет, {message.from_user.first_name}!", reply_markup=markup)
    
def start_bot():
    while True:
        try:
            logging.info("Starting Telegram bot...")
            bot.polling(none_stop=True, interval=1, timeout=30)
        except Exception as e:
            logging.error(f"Bot crashed due to: {e}", exc_info=True)
            logging.info("Restarting bot in 5 seconds...")
            time.sleep(5)  # Wait before restarting            
            
if __name__ == "__main__":
    start_bot()