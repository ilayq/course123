import pika
import redis
import json
import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class RabbitMQManager:
    @staticmethod
    def get_connection():
        credentials = pika.PlainCredentials('admin', 'admin123')
        parameters = pika.ConnectionParameters(
            host='rabbitmq',
            port=5672,
            virtual_host='/auction',
            credentials=credentials,
            heartbeat=600,
            blocked_connection_timeout=300
        )
        return pika.BlockingConnection(parameters)

    @staticmethod
    def setup_infrastructure(channel):
        try:
            channel.exchange_declare(
                exchange='auction_events',
                exchange_type='topic',
                durable=True
            )
            
            channel.queue_declare(
                queue='bid_queue',
                durable=True,
                arguments={
                    'x-message-ttl': 86400000,
                    'x-queue-type': 'classic'
                }
            )
            
            channel.queue_bind(
                exchange='auction_events',
                queue='bid_queue',
                routing_key='bid.*'
            )
            
            logger.info("RabbitMQ infrastructure verified")
        except Exception as e:
            logger.error(f"Failed to setup RabbitMQ: {e}")
            raise

def main():
    redis_client = redis.Redis(host='redis', port=6379, db=0)
    
    while True:
        try:
            connection = RabbitMQManager.get_connection()
            channel = connection.channel()
            
            RabbitMQManager.setup_infrastructure(channel)

            def callback(ch, method, properties, body):
                try:
                    event = json.loads(body)
                    if event.get('event') == 'BidPlaced':
                        logger.info(f"Processing bid: {event['lot_id']}")
                        
                        redis_client.hset(
                            f"lot:{event['lot_id']}",
                            mapping={
                                'current_price': event['amount'],
                                'last_bidder': event['user_id']
                            }
                        )
                        
                        channel.basic_publish(
                            exchange='auction_events',
                            routing_key=f"bid_processed.{event['lot_id']}",
                            body=json.dumps({
                                'event': 'BidProcessed',
                                **event
                            }),
                            properties=pika.BasicProperties(
                                delivery_mode=2,
                                content_type='application/json'
                            )
                        )
                        
                except Exception as e:
                    logger.error(f"Bid processing error: {e}")

            channel.basic_consume(
                queue='bid_queue',
                on_message_callback=callback,
                auto_ack=True
            )
            
            logger.info("Bidding service started successfully")
            channel.start_consuming()
            
        except pika.exceptions.AMQPChannelError as e:
            logger.error(f"Channel error: {e}, recreating channel...")
            time.sleep(5)
        except pika.exceptions.AMQPConnectionError:
            logger.error("Connection lost, reconnecting...")
            time.sleep(5)
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()