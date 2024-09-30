FROM python:3.9-slim

# Устанавливаем необходимые пакеты
RUN apt-get update && apt-get install -y git

# Устанавливаем рабочую директорию внутри контейнера
WORKDIR /app

# Копируем файлы вашего проекта в контейнер
COPY . .

# Устанавливаем зависимости из requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Определяем команду для запуска приложения
CMD ["python", "finance_bot.py"]
