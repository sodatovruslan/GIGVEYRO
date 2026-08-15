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

## Запуск сервера

```powershell
uvicorn app.main:app --reload
```

## Проверка

- Health check: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)
- Swagger UI: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
