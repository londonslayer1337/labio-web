import os
import ssl
from contextlib import asynccontextmanager
from typing import List

import asyncpg
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from passlib.context import CryptContext
from pydantic import BaseModel, Field

# хэшик
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# пул
db_pool: asyncpg.Pool = None

DATABASE_URL = os.environ.get("DATABASE_URL")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool
    print(
        f"--- ИНИЦИАЛИЗАЦИЯ: DATABASE_URL = {DATABASE_URL[:25] if DATABASE_URL else 'НЕ НАЙДЕНА'}... ---"
    )

    if not DATABASE_URL:
        print("❌ CRITICAL ERROR: Переменная DATABASE_URL пустая или не задана!")
    else:
        try:
            dsn = DATABASE_URL.strip()

            # асинкпг
            if dsn.startswith("postgres://"):
                dsn = dsn.replace("postgres://", "postgresql://", 1)

            # настройки хуйни
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

            print("Попытка подключения к бд")

            db_pool = await asyncpg.create_pool(
                dsn=dsn,
                ssl=ctx,
                min_size=1,
                max_size=10,
                timeout=15.0,
            )
            print("✅ Успешное подключение к бд!")

            async with db_pool.acquire() as conn:
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        id SERIAL PRIMARY KEY,
                        username VARCHAR(64) UNIQUE NOT NULL,
                        password_hash TEXT NOT NULL,
                        display_name VARCHAR(128) NOT NULL,
                        phone VARCHAR(32),
                        is_admin BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );

                    CREATE TABLE IF NOT EXISTS messages (
                        id SERIAL PRIMARY KEY,
                        sender_username VARCHAR(64) NOT NULL,
                        sender_name VARCHAR(128) NOT NULL,
                        text TEXT NOT NULL,
                        is_pinned BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                """
                )
                print("✅ Таблицы созданы.")
        except Exception as e:
            print(f"❌ ПОЛНАЯ ОШИБКА ПОДКЛЮЧЕНИЯ К БД: {type(e).__name__}: {e}")

    yield

    if db_pool:
        await db_pool.close()
        print("Соединение с базой данных закрыто.")


app = FastAPI(title="Labio Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# падантик
class UserRegister(BaseModel):
    username: str = Field(..., example="@username")
    password: str
    display_name: str
    phone: str = None


class UserLogin(BaseModel):
    username: str = Field(..., example="@username")
    password: str


# вебсокет менеджер
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


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def normalize_username(username: str) -> str:
    username = username.strip()
    if not username.startswith("@"):
        return f"@{username}"
    return username


# апи эндпоинты
@app.get("/", response_class=HTMLResponse)
async def get_index():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    return HTMLResponse(content="<h1>Labio Backend Active</h1>", status_code=200)


@app.post("/api/register")
async def register(user: UserRegister):
    if not db_pool:
        raise HTTPException(
            status_code=500,
            detail="База данных не подключена (db_pool is None). Проверьте логи сервера.",
        )

    clean_username = normalize_username(user.username)

    async with db_pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM users WHERE username = $1", clean_username
        )
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Пользователь {clean_username} уже зарегистрирован",
            )

        hashed_pwd = hash_password(user.password)
        await conn.execute(
            """
            INSERT INTO users (username, password_hash, display_name, phone)
            VALUES ($1, $2, $3, $4)
        """,
            clean_username,
            hashed_pwd,
            user.display_name,
            user.phone,
        )

    return {"status": "ok", "message": f"Пользователь {clean_username} создан!"}


@app.post("/api/login")
async def login(user: UserLogin):
    if not db_pool:
        raise HTTPException(
            status_code=500, detail="База данных не подключена"
        )

    clean_username = normalize_username(user.username)

    async with db_pool.acquire() as conn:
        db_user = await conn.fetchrow(
            "SELECT username, password_hash, display_name, is_admin FROM users WHERE username = $1",
            clean_username,
        )

        if not db_user or not verify_password(
            user.password, db_user["password_hash"]
        ):
            raise HTTPException(
                status_code=400, detail="Неверный @username или пароль"
            )

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
        raise HTTPException(
            status_code=500, detail="База данных не подключена"
        )

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
                "created_at": r["created_at"].isoformat()
                if r["created_at"]
                else None,
            }
            for r in rows
        ]


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "message":
                sender_username = normalize_username(
                    data.get("sender_username", "@anon")
                )
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

                        await manager.broadcast(
                            {
                                "type": "new_message",
                                "message": {
                                    "id": row["id"],
                                    "sender_username": sender_username,
                                    "sender_name": sender_name,
                                    "text": text,
                                    "is_pinned": False,
                                    "created_at": row["created_at"].isoformat(),
                                },
                            }
                        )
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"Ошибка WS: {e}")
        manager.disconnect(websocket)
