import os

class Config:
    RABBITMQ = {
        "host": os.getenv("RABBITMQ_HOST", "rabbitmq"),
        "port": int(os.getenv("RABBITMQ_PORT", 5672)),
        "virtual_host": os.getenv("RABBITMQ_VHOST", "/auction"),
        "credentials": {
            "username": os.getenv("RABBITMQ_USER", "admin"),
            "password": os.getenv("RABBITMQ_PASS", "admin123")
        },
        "heartbeat": 60,
        "timeout": 10
    }

    REDIS = {
        "host": os.getenv("REDIS_HOST", "redis"),
        "port": int(os.getenv("REDIS_PORT", 6379)),
        "db": int(os.getenv("REDIS_DB", 0)),
        "socket_timeout": 5
    }