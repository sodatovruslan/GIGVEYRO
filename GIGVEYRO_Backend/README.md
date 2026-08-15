# GIGVEYRO Backend

Backend-проект GIGVEYRO на Python (FastAPI).

## Стек

- Python 3.11
- FastAPI
- Uvicorn
- SQLAlchemy (async) + asyncpg
- Alembic
- Pydantic Settings

## Установка

### 1. Создать виртуальное окружение

```powershell
python -m venv .venv
```

### 2. Активировать окружение

```powershell
.\.venv\Scripts\Activate.ps1
```

Если PowerShell блокирует запуск скрипта:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### 3. Установить зависимости

```powershell
pip install -r requirements.txt
```

### 4. Настроить переменные окружения

Скопируй `.env.example` в `.env` и заполни `DATABASE_URL` реальными значениями:

```powershell
copy .env.example .env
```

## PostgreSQL

Проект использует PostgreSQL (async-драйвер `asyncpg`).

### Формат DATABASE_URL

```env
DATABASE_URL=postgresql+asyncpg://<user>:<password>@<host>:<port>/<database>
```

### Создание development database и пользователя

Локально должен быть установлен и запущен PostgreSQL. Подключись под суперпользователем (например, `postgres`) и выполни:

```sql
CREATE DATABASE gigveyro;
CREATE USER gigveyro_user WITH PASSWORD 'CHANGE_ME';
GRANT ALL PRIVILEGES ON DATABASE gigveyro TO gigveyro_user;
```

После этого пропиши реальные значения в `.env`. `.env` не коммитится в Git — только `.env.example` с плейсхолдерами.

### Применение миграций

```powershell
alembic upgrade head
```

### Проверка текущей ревизии

```powershell
alembic current
```

## Запуск сервера

```powershell
uvicorn app.main:app --reload
```

## Проверка

- Application health check: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)
- Database health check: [http://127.0.0.1:8000/health/db](http://127.0.0.1:8000/health/db)
- Swagger UI: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

## Тесты

```powershell
pytest
```

## Lint

```powershell
ruff check .
```
