"""Корневая точка входа для хостингов, ожидающих /app/main.py.

Основная реализация находится в пакете app.main.
"""
import asyncio

from app.main import main

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
