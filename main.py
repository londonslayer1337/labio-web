import os
import sys
from typing import List

# --- СЕРВЕРНАЯ ЧАСТЬ (FastAPI) ---
if "uvicorn" in sys.argv[0] or __name__ == "main":
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
    from fastapi.responses import HTMLResponse
    from fastapi.staticfiles import StaticFiles

    app = FastAPI()

    os.makedirs("uploads", exist_ok=True)
    app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
import os
import sys
import json
from typing import List

if "uvicorn" in sys.argv[0] or __name__ == "main":
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse

    app = FastAPI()

    class ConnectionManager:
        def __init__(self):
            self.active_connections: List[WebSocket] = []

        async def connect(self, websocket: WebSocket):
            await websocket.accept()
            self.active_connections.append(websocket)

        def disconnect(self, websocket: WebSocket):
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)

        async def broadcast(self, message: str):
            for connection in self.active_connections:
                await connection.send_text(message)

    manager = ConnectionManager()

    @app.get("/")
    async def get_web_client():
        if os.path.exists("index.html"):
            with open("index.html", "r", encoding="utf-8") as f:
                return HTMLResponse(content=f.read())
        return HTMLResponse(content="<h1>index.html not found</h1>")

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await manager.connect(websocket)
        try:
            while True:
                data = await websocket.receive_text()
                await manager.broadcast(data)
        except WebSocketDisconnect:
            manager.disconnect(websocket)

