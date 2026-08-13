import os
from contextlib import asynccontextmanager
from typing import List

import asyncpg
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from passlib.context import CryptContext
from pydantic import BaseModel

# --- НАСТРОЙКИ ХЭШИРОВАНИЯ ---
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- ГЛОБАЛЬНЫЙ ПУЛ СОЕДИНЕНИЙ ---
db_pool: asyncpg.Pool = None
DATABASE_URL = os.environ.get("postgresql://postgres:[Zima26032022123]@db.qcygykbubjgmvgnuyzzw.supabase.co:5432/postgres")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool
    if not DATABASE_URL:
        print("ВНИМАНИЕ: Переменная DATABASE_URL не задана!")
    else:
        db_pool = await asyncpg.create_pool(dsn=DATABASE_URL)
        print("Подключение к базе данных Supabase установлено.")

        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    phone TEXT,
                    is_admin BOOLEAN DEFAULT FALSE
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    sender_username TEXT NOT NULL,
                    sender_name TEXT NOT NULL,
                    text TEXT NOT NULL,
                    is_pinned BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
            """
            )

    yield

    if db_pool:
        await db_pool.close()
        print("Соединение с базой данных закрыто.")


app = FastAPI(title="Labio Backend", lifespan=lifespan)

# --- CORS МИДЛВАРЬ ДЛЯ РАБОТЫ НА ЛЮБЫХ ДОМЕНАХ ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- СХЕМЫ PYDANTIC ---
class UserRegister(BaseModel):
    username: str
    password: str
    display_name: str
    phone: str = None


class UserLogin(BaseModel):
    username: str
    password: str


# --- МЕНЕДЖЕР WEBSOCKET ---
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
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass


manager = ConnectionManager()


# --- ХЕЛПЕРЫ ДЛЯ ХЭШИРОВАНИЯ ---
def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


# --- ЭНДПОИНТЫ API ---
@app.get("/", response_class=HTMLResponse)
async def get_index():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    return HTMLResponse(
        content="<h1>Labio Messenger Backend</h1><p>Сервер работает корректно.</p>",
        status_code=200,
    )


@app.post("/api/register")
async def register(user: UserRegister):
    if not db_pool:
        raise HTTPException(status_code=500, detail="База данных не подключена")

    async with db_pool.acquire() as conn:
        existing_user = await conn.fetchrow(
            "SELECT id FROM users WHERE username = $1", user.username
        )
        if existing_user:
            raise HTTPException(
                status_code=400, detail="Пользователь с таким логином уже существует"
            )

        hashed_pwd = hash_password(user.password)
        await conn.execute(
            """
            INSERT INTO users (username, password_hash, display_name, phone)
            VALUES ($1, $2, $3, $4)
        """,
            user.username,
            hashed_pwd,
            user.display_name,
            user.phone,
        )

    return {"status": "ok", "message": "Регистрация прошла успешно"}


@app.post("/api/login")
async def login(user: UserLogin):
    if not db_pool:
        raise HTTPException(status_code=500, detail="База данных не подключена")

    async with db_pool.acquire() as conn:
        db_user = await conn.fetchrow(
            "SELECT username, password_hash, display_name, is_admin FROM users WHERE username = $1",
            user.username,
        )

        if not db_user or not verify_password(user.password, db_user["password_hash"]):
            raise HTTPException(status_code=400, detail="Неверный логин или пароль")

        return {
            "status": "ok",
            "user": {
                "username": db_user["username"],
                "display_name": db_user["display_name"],
                "is_admin": db_user["is_admin"],
            },
        }


@app.get("/api/messages")
async def get_messages():
    if not db_pool:
        raise HTTPException(status_code=500, detail="База данных не подключена")

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, sender_username, sender_name, text, is_pinned, created_at 
            FROM messages 
            ORDER BY id ASC 
            LIMIT 100
        """
        )
        return [
            {
                "id": r["id"],
                "sender_username": r["sender_username"],
                "sender_name": r["sender_name"],
                "text": r["text"],
                "is_pinned": r["is_pinned"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]


# --- WEBSOCKET ДЛЯ ЧАТА В РЕАЛЬНОМ ВРЕМЕНИ ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "message":
                sender_username = data.get("sender_username", "Anon")
                sender_name = data.get("sender_name", "Аноним")
                text = data.get("text", "")

                if text.strip() and db_pool:
                    async with db_pool.acquire() as conn:
                        row = await conn.fetchrow(
                            """
                            INSERT INTO messages (sender_username, sender_name, text)
                            VALUES ($1, $2, $3)
                            RETURNING id, created_at
                        """,
                            sender_username,
                            sender_name,
                            text,
                        )

                        await manager.broadcast({
                            "type": "new_message",
                            "message": {
                                "id": row["id"],
                                "sender_username": sender_username,
                                "sender_name": sender_name,
                                "text": text,
                                "is_pinned": False,
                                "created_at": row["created_at"].isoformat(),
                            },
                        })
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"Ошибка WebSocket: {e}")
        manager.disconnect(websocket)
