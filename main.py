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
        with open("index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())

    @app.post("/upload")
    async def upload_image(file: UploadFile = File(...)):
        file_path = f"uploads/{file.filename}"
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
        return {"url": f"/uploads/{file.filename}"}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await manager.connect(websocket)
        try:
            while True:
                data = await websocket.receive_text()
                await manager.broadcast(data)
        except WebSocketDisconnect:
            manager.disconnect(websocket)

# --- КЛИЕНТСКАЯ ЧАСТЬ (KivyMD) ---
def run_kivy_app():
    import asyncio
    import threading
    import requests
    from kivymd.app import MDApp
    from kivymd.uix.boxlayout import MDBoxLayout
    from kivymd.uix.button import MDRaisedButton
    from kivymd.uix.textfield import MDTextField
    from kivymd.uix.label import MDLabel
    from kivy.clock import Clock
    import websockets

    SERVER_HOST = "127.0.0.1:8000"  # Позже замапите на IP вашего сервера

    class OpenMSApp(MDApp):
        def build(self):
            self.theme_cls.theme_style = "Dark"
            self.layout = MDBoxLayout(orientation='vertical', padding=10, spacing=10)
            self.chat_label = MDLabel(text="Подключение к OpenMS...\n", halign="left", valign="top")
            self.layout.add_widget(self.chat_label)

            input_layout = MDBoxLayout(orientation='horizontal', spacing=10, size_hint_y=None, height="50dp")
            self.text_input = MDTextField(hint_text="Введите сообщение...")
            send_btn = MDRaisedButton(text="Отправить", on_release=self.send_message)
            
            input_layout.add_widget(self.text_input)
            input_layout.add_widget(send_btn)
            self.layout.add_widget(input_layout)

            threading.Thread(target=self.start_websocket_thread, daemon=True).start()
            return self.layout

        def append_message(self, text):
            Clock.schedule_once(lambda dt: setattr(self.chat_label, 'text', self.chat_label.text + f"{text}\n"))

        def start_websocket_thread(self):
            asyncio.run(self.websocket_loop())

        async def websocket_loop(self):
            url = f"ws://{SERVER_HOST}/ws"
            try:
                async with websockets.connect(url) as ws:
                    self.ws = ws
                    self.append_message("[Система] Подключено!")
                    while True:
                        msg = await ws.recv()
                        self.append_message(f"Сообщение: {msg}")
            except Exception as e:
                self.append_message(f"[Ошибка] {e}")

        def send_message(self, instance):
            msg = self.text_input.text
            if msg and hasattr(self, 'ws'):
                asyncio.run_coroutine_threadsafe(self.ws.send(msg), asyncio.get_event_loop())
                self.text_input.text = ""

    OpenMSApp().run()

if __name__ == '__main__':
    if "uvicorn" not in sys.argv[0]:
 
              run_kivy_app()
