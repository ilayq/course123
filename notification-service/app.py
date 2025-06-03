from config import Config
import pika
import json
import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def connect_rabbitmq():
    credentials = pika.PlainCredentials(
        Config.RABBITMQ["credentials"]["username"],
        Config.RABBITMQ["credentials"]["password"]
    )
    parameters = pika.ConnectionParameters(
        host=Config.RABBITMQ["host"],
        port=Config.RABBITMQ["port"],
        virtual_host=Config.RABBITMQ["virtual_host"],
        credentials=credentials,
        heartbeat=Config.RABBITMQ["heartbeat"]
    )
    return pika.BlockingConnection(parameters)

def setup_rabbitmq(channel):
    try:
        # на всякий случай :)
        channel.exchange_declare(
            exchange='auction_events',
            exchange_type='topic',
            durable=True,
            passive=True
        )
        
        channel.queue_declare(
            queue='notification_queue',
            durable=True,
            arguments={
                'x-message-ttl': 86400000,
                'x-queue-type': 'classic'
            }
        )
        
        channel.queue_bind(
            exchange='auction_events',
            queue='notification_queue',
            routing_key='bid_processed.*'
        )
        
    except Exception as e:
        logger.error(f"RabbitMQ setup error: {e}")
        raise

def main():
    while True:
        try:
            connection = connect_rabbitmq()
            channel = connection.channel()
            
            setup_rabbitmq(channel)

            def callback(ch, method, properties, body):
                try:
                    message = json.loads(body)
                    logger.info(f"New notification: {message}")
                except Exception as e:
                    logger.error(f"Error processing message: {e}")

            channel.basic_consume(
                queue='notification_queue',
                on_message_callback=callback,
                auto_ack=True
            )

            logger.info("Notification service started successfully")
            channel.start_consuming()
            
        except Exception as e:
            logger.error(f"Error: {e}, retrying in 5 seconds...")
            time.sleep(5)

if __name__ == "__main__":
    main()
