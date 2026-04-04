import asyncio
from contextlib import asynccontextmanager
from queue import Empty, Queue, ShutDown
import threading
from typing import AsyncGenerator, Generator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn

from .packets import PacketData, RawPacket


startup_event = threading.Event()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    startup_event.set()
    yield


app = FastAPI(lifespan=lifespan)
app.state.send_queue = Queue()
app.state.receive_queue = Queue()


def get_raw_packet() -> dict:
    """Get a packet from the queue.
    :return: A packet
    :rtype: dict
    """
    try:
        return app.state.receive_queue.get_nowait()
    except Empty:
        return {}


def send_packet_data(data: PacketData) -> None:
    """Send packet data to the server

    :param data: The packet data to send
    :type data: PacketData
    """
    try:
        app.state.send_queue.put(data.to_dict())
    except ShutDown:
        return  # TODO: log warning


def run_api_server() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8000)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()

    async def receive() -> None:
        while True:
            data = await websocket.receive_json()
            websocket.app.state.receive_queue.put(data)

    async def send() -> None:
        while True:
            packet_data = await asyncio.to_thread(
                websocket.app.state.send_queue.get, timeout=0.5
            )
            items = [packet_data]
            while not websocket.app.state.send_queue.empty():
                items.append(websocket.app.state.send_queue.get_nowait())
            await websocket.send_json({"from": "server", "data": items})

    receive_task = asyncio.create_task(receive())
    send_task = asyncio.create_task(send())
    try:
        await asyncio.gather(receive_task, send_task)
    except WebSocketDisconnect:
        receive_task.cancel()
        send_task.cancel()
