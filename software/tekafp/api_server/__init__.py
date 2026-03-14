from fastapi import FastAPI
from starlette.websockets import WebSocket
import uvicorn

from tekafp.api_server.packets import BY_TYPE


async def decode_packet(packet: dict) -> None:
    for data in packet.values():
        BY_TYPE[data["$type"]](data)
app = FastAPI()

def run_api_server() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8000)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    while True:
        data = await websocket.receive_json()
        await decode_packet(data)
        await websocket.send_json(data)
