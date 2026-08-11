import os
import sys
import json
from typing import List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Header
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from passlib.context import CryptContext
import asyncpg

app = FastAPI()

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Хеширование паролей
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Берем ссылку на Supabase из переменных окружения (в Hugging Face Settings)
DATABASE_URL = os.environ.get("postgresql://postgres:[Zima26032022!?]@db.qcygykbubjgmvgnuyzzw.supabase.co:5432/postgres")

db_pool = None

@app.on_event("startup")
async def startup():
    global db_pool
    if DATABASE_URL:
        # asyncpg требует ssl для подключения к Supabase
        db_pool = await asyncpg.create_pool(DATABASE_URL, ssl="require")
    else:
        print("ВНИМАНИЕ: DATABASE_URL не задан в переменных окружения!")

@app.on_event("shutdown")
async def shutdown():
    if db_pool:
        await db_pool.close()

# --- МЕНЕДЖЕР ВЕБСОКЕТОВ ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        payload = json.dumps(message)
        for connection in self.active_connections:
            try:
                await connection.send_text(payload)
            except Exception:
                pass

manager = ConnectionManager()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

# --- ЭНДПОИНТЫ АВТОРИЗАЦИИ И ПОЛЬЗОВАТЕЛЕЙ ---
@app.post("/api/register")
async def register(data: dict):
    username = data.get("username", "").strip().lower()
    password = data.get("password", "")
    display_name = data.get("display_name", "").strip()

    if not username or not password or not display_name:
        raise HTTPException(status_code=400, detail="Заполните все поля")

    if not username.startswith("@"):
        username = "@" + username

    hashed = get_password_hash(password)

    async with db_pool.acquire() as conn:
        # Проверяем, существует ли пользователь
        existing = await conn.fetchrow("SELECT id FROM users WHERE username = $1", username)
        if existing:
            raise HTTPException(status_code=400, detail="Этот @username уже занят")
        
        # Регистрируем (первый пользователь может быть сделан админом)
        await conn.execute(
            "INSERT INTO users (username, password_hash, display_name) VALUES ($1, $2, $3)",
            username, hashed, display_name
        )

    return {"status": "ok", "message": "Регистрация успешна"}

@app.post("/api/login")
async def login(data: dict):
    username = data.get("username", "").strip().lower()
    password = data.get("password", "")

    if not username.startswith("@"):
        username = "@" + username

    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE username = $1", username)
        if not user or not verify_password(password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Неверный username или пароль")

        return {
            "status": "ok",
            "username": user["username"],
            "display_name": user["display_name"],
            "phone": user["phone"],
            "is_admin": user["is_admin"]
        }

@app.get("/api/check-username/{username}")
async def check_username(username: str):
    if not username.startswith("@"):
        username = "@" + username

    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT id FROM users WHERE username = $1", username.lower())
        return {"available": user is None}

# --- УПРАВЛЕНИЕ НАСТРОЙКАМИ И АНОНИМНЫМ НОМЕРОМ ---
@app.post("/api/user/update-phone")
async def update_phone(data: dict):
    username = data.get("username")
    phone = data.get("phone")

    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET phone = $1 WHERE username = $2", phone, username)
    return {"status": "ok"}

# --- СООБЩЕНИЯ И ВЕБСОКЕТЫ ---
@app.get("/api/messages")
async def get_messages():
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, sender_username, sender_name, text, is_pinned, created_at FROM messages ORDER BY id ASC LIMIT 100"
        )
        messages = []
        for r in rows:
            messages.append({
                "id": r["id"],
                "username": r["sender_username"],
                "sender": r["sender_name"],
                "text": r["text"],
                "is_pinned": r["is_pinned"]
            })
        return messages

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            raw_data = await websocket.receive_text()
            data = json.loads(raw_data)
            action = data.get("action", "send")

            async with db_pool.acquire() as conn:
                if action == "send":
                    row = await conn.fetchrow(
                        "INSERT INTO messages (sender_username, sender_name, text) VALUES ($1, $2, $3) RETURNING id",
                        data["username"], data["sender"], data["text"]
                    )
                    broadcast_data = {
                        "type": "new_message",
                        "id": row["id"],
                        "username": data["username"],
                        "sender": data["sender"],
                        "text": data["text"],
                        "is_pinned": False
                    }
                    await manager.broadcast(broadcast_data)

                elif action == "delete":
                    msg_id = data.get("id")
                    await conn.execute("DELETE FROM messages WHERE id = $1", msg_id)
                    await manager.broadcast({"type": "delete_message", "id": msg_id})

                elif action == "edit":
                    msg_id = data.get("id")
                    new_text = data.get("text")
                    await conn.execute("UPDATE messages SET text = $1 WHERE id = $2", new_text, msg_id)
                    await manager.broadcast({"type": "edit_message", "id": msg_id, "text": new_text})

                elif action == "pin":
                    msg_id = data.get("id")
                    is_pinned = data.get("is_pinned")
                    await conn.execute("UPDATE messages SET is_pinned = $1 WHERE id = $2", is_pinned, msg_id)
                    await manager.broadcast({"type": "pin_message", "id": msg_id, "is_pinned": is_pinned})

    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.get("/")
async def get_web_client():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>index.html not found</h1>")
