import json

import sentry_sdk
import sentry_sdk.logger as sentry_logger
from redis.asyncio import Redis


class EventChannel:
    def __init__(self, async_redis: Redis, channel: str):
        self.channel = channel
        self.async_redis = async_redis

    MESSAGE_TIMEOUT = 10

    @property
    def channel(self):
        return self.channel

    @channel.setter
    def channel(self):
        self.channel = self.channel

    def pubsub_async(self):
        return self.async_redis.pubsub()

    async def subscribe_async(self):
        try:
            pubsub = self.pubsub_async()
            await pubsub.subscribe(self.channel)
            sentry_logger.info(
                "Successfully subscribed to channel", extra={"channel": self.channel}
            )
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            sentry_logger.error("Error subscribing to channel", extra={"channel": self.channel})

    async def unsubscribe_async(self):
        try:
            pubsub = self.pubsub_async()
            await pubsub.unsubscribe(self.channel)
            sentry_logger.info(
                "Successfully unsubscribed from channel", extra={"channel": self.channel}
            )
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            sentry_logger.error("Error unsubscribing from channel", extra={"channel": self.channel})

    async def publish_async(self, message: dict):
        try:
            await self.async_redis.publish(self.channel, json.dumps(message))
            sentry_logger.info(
                "Message published to channel", extra={"channel": self.channel, "meta": message}
            )
        except TypeError:
            sentry_logger.error(
                "Invalid payload received", extra={"channel": self.channel, "meta": message}
            )
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            sentry_logger.error(
                "Error publishing message", extra={"channel": self.channel, "meta": message}
            )

    async def get_message_async(self):
        try:
            await self.subscribe_async()

            message = await self.pubsub_async().get_message(
                ignore_subscribe_messages=True, timeout=self.MESSAGE_TIMEOUT
            )

            if message:
                return json.loads(message["data"])
            return
        except (json.JSONDecodeError, TypeError):
            sentry_logger.error("Invalid payload received", extra={"channel": self.channel})
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            sentry_logger.error(
                "Error occured while retrieving message from channel",
                extra={"channel": self.channel},
            )
        finally:
            await self.unsubscribe_async()
