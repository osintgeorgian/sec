"""Запуск только FastAPI (для деплоя или отдельного процесса)"""
import os
from dotenv import load_dotenv
import uvicorn

load_dotenv()

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", 8000)),
        reload=True
    )
