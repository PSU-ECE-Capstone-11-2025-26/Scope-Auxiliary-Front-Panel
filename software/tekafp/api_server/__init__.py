import asyncio
from queue import Queue, ShutDown

from fastapi import FastAPI
from starlette.websockets import WebSocket, WebSocketDisconnect
import uvicorn

from tekafp.api_server.packets import BY_TYPE


app = FastAPI()
app.state.send_queue = Queue()
app.state.receive_queue = Queue()


def get_packets() -> dict:
    packet = app.state.receive_queue.get()
    for data in packet.values():
        yield BY_TYPE[data["$type"]](data)


def send_packet(packet: dict) -> None:
    try:
        app.state.send_queue.put(packet)
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
            packet = await asyncio.to_thread(
                websocket.app.state.send_queue.get, timeout=0.5
            )
            await websocket.send_json(packet)

    receive_task = asyncio.create_task(receive())
    send_task = asyncio.create_task(send())
    try:
        await asyncio.gather(receive_task, send_task)
    except WebSocketDisconnect:
        receive_task.cancel()
        send_task.cancel()
