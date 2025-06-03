from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import aio_pika
import redis
import json
import asyncio
import logging
from contextlib import asynccontextmanager


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.active_connections = {}

    async def connect(self, websocket: WebSocket, lot_id: str):
        await websocket.accept()
        if lot_id not in self.active_connections:
            self.active_connections[lot_id] = []
        self.active_connections[lot_id].append(websocket)

    async def disconnect(self, websocket: WebSocket, lot_id: str):
        if lot_id in self.active_connections:
            self.active_connections[lot_id].remove(websocket)

    async def broadcast(self, lot_id: str, message: str):
        if lot_id in self.active_connections:
            for connection in self.active_connections[lot_id]:
                await connection.send_text(message)

manager = ConnectionManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = redis.Redis(host='redis', port=6379, db=0)

    try:
        connection = await aio_pika.connect_robust(
            host="rabbitmq",
            port=5672,
            virtualhost="/auction",
            login="admin",
            password="admin123",
            timeout=10
        )
        app.state.rabbitmq = connection
        channel = await connection.channel()

        await channel.declare_exchange(
            "auction_events",
            aio_pika.ExchangeType.TOPIC,
            durable=True
        )

        app.state.listener_task = asyncio.create_task(rabbitmq_listener(connection))
        logger.info("RabbitMQ connected successfully")

        yield

        app.state.listener_task.cancel()
        await connection.close()
    except Exception as e:
        logger.error(f"Failed to connect to RabbitMQ: {e}")
        raise

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

async def rabbitmq_listener(connection):
    try:
        channel = await connection.channel()
        queue = await channel.declare_queue(
            "ws_notifications",
            durable=True
        )

        await queue.bind(
            exchange="auction_events",
            routing_key="bid_processed.*"
        )

        async with queue.iterator() as queue_iter:
            async for message in queue_iter:
                try:
                    async with message.process():
                        data = json.loads(message.body.decode())
                        await manager.broadcast(
                            data['lot_id'],
                            message.body.decode()
                        )
                except Exception as e:
                    logger.error(f"Message processing error: {e}")
    except Exception as e:
        logger.error(f"RabbitMQ listener error: {e}")

@app.websocket("/ws/lots/{lot_id}")
async def websocket_endpoint(websocket: WebSocket, lot_id: str):
    await manager.connect(websocket, lot_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket, lot_id)

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.get("/lots/{lot_id}")
async def get_lot(lot_id: str):
    lot_data = app.state.redis.get(f"lot:{lot_id}")
    if not lot_data:
        raise HTTPException(status_code=404, detail="Lot not found")

    return json.loads(lot_data)


@app.post("/lots/{lot_id}")
async def create_or_update_lot(lot_id: str, lot_data: dict):
    app.state.redis.set(f"lot:{lot_id}", json.dumps(lot_data))
    return {"status": "ok"}


@app.post("/lots/{lot_id}/bid")
async def place_bid(lot_id: str, request: Request):
    try:
        data = await request.json()
        user_id = data.get("user_id")
        amount = data.get("amount")

        if not user_id or not amount:
            raise HTTPException(status_code=400, detail="Missing user_id or amount")

        lot_data = app.state.redis.get(f"lot:{lot_id}")
        if not lot_data:
            raise HTTPException(status_code=404, detail="Lot not found")

        lot = json.loads(lot_data)

        if amount <= lot.get("current_price", 0):
            raise HTTPException(status_code=400, detail="Bid must be higher than current price")

        lot["current_price"] = amount
        lot["last_bidder"] = user_id
        app.state.redis.set(f"lot:{lot_id}", json.dumps(lot))

        channel = await app.state.rabbitmq.channel()
        exchange = await channel.get_exchange("auction_events")

        await exchange.publish(
            aio_pika.Message(
                body=json.dumps({
                    "event": "BidProcessed",
                    "lot_id": lot_id,
                    "new_price": amount,
                    "bidder": user_id
                }).encode()
            ),
            routing_key=f"bid_processed.{lot_id}"
        )

        return {"status": "success", "new_price": amount}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

app.mount("/static", StaticFiles(directory="static"), name="static")