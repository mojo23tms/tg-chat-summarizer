import time

from . import config


def _chat_pk(chat_id):
    return f"CHAT#{chat_id}"


def _owner_pk(user_id):
    return f"OWNER#{user_id}"


def _user_pk(user_id):
    return f"USER#{user_id}"


def _chat_index_pk():
    return "CHATS"


def _chat_index_sk(chat_id):
    return f"CHAT#{chat_id}"


def _message_sk(ts, msg_id):
    return f"MSG#{int(ts):020d}#{int(msg_id):020d}"


class DynamoDBStorage:
    def __init__(self, table_name=None, dynamodb_resource=None, ttl_days=None):
        if dynamodb_resource is None:
            import boto3

            dynamodb_resource = boto3.resource("dynamodb")
        self.table = dynamodb_resource.Table(table_name or config.DDB_TABLE_NAME)
        self.ttl_days = config.MESSAGE_TTL_DAYS if ttl_days is None else ttl_days

    def log_message(
        self, chat_id, msg_id, user_id, user_name, text, ts=None, expires_at=None
    ):
        ts = int(time.time() if ts is None else ts)
        item = {
            "pk": _chat_pk(chat_id),
            "sk": _message_sk(ts, msg_id),
            "msg_id": int(msg_id),
            "user_id": int(user_id),
            "user_name": user_name,
            "text": text,
            "ts": ts,
            "expires_at": int(expires_at or ts + self.ttl_days * 86400),
        }
        self.table.put_item(Item=item)
        self.table.put_item(
            Item={
                "pk": _chat_index_pk(),
                "sk": _chat_index_sk(chat_id),
                "chat_id": int(chat_id),
                "last_seen_at": ts,
            }
        )

    def list_chat_ids(self):
        indexed = self._list_indexed_chat_ids()
        if indexed:
            return indexed
        return self._scan_chat_ids()

    def _list_indexed_chat_ids(self):
        response = self.table.query(
            KeyConditionExpression="pk = :pk",
            ExpressionAttributeValues={":pk": _chat_index_pk()},
        )
        return sorted({int(item["chat_id"]) for item in response.get("Items", [])})

    def _scan_chat_ids(self):
        seen = set()
        kwargs = {"ProjectionExpression": "pk"}
        while True:
            response = self.table.scan(**kwargs)
            for item in response.get("Items", []):
                pk = item.get("pk", "")
                if pk.startswith("CHAT#"):
                    seen.add(int(pk.removeprefix("CHAT#")))
            if "LastEvaluatedKey" not in response:
                break
            kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        return sorted(seen)

    def recent_messages(self, chat_id, n):
        response = self.table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": _chat_pk(chat_id), ":prefix": "MSG#"},
            ScanIndexForward=False,
            Limit=int(n),
        )
        rows = [
            {"user_name": item["user_name"], "text": item["text"], "ts": int(item["ts"])}
            for item in response.get("Items", [])
        ]
        rows.reverse()
        return rows

    def get_settings(self, chat_id):
        settings = dict(config.DEFAULTS)
        response = self.table.get_item(Key={"pk": _chat_pk(chat_id), "sk": "SETTINGS"})
        item = response.get("Item") or {}
        for key in config.DEFAULTS:
            if key in item:
                settings[key] = item[key]
        return settings

    def set_setting(self, chat_id, key, value):
        self.table.update_item(
            Key={"pk": _chat_pk(chat_id), "sk": "SETTINGS"},
            UpdateExpression="SET #key = :value",
            ExpressionAttributeNames={"#key": key},
            ExpressionAttributeValues={":value": value},
        )

    def set_pending_input(self, user_id, action, target_chat_id, now=None, ttl_seconds=600):
        now = int(time.time() if now is None else now)
        self.table.put_item(
            Item={
                "pk": _user_pk(user_id),
                "sk": "PENDING",
                "action": action,
                "target_chat_id": int(target_chat_id),
                "created_at": now,
                "expires_at": now + int(ttl_seconds),
            }
        )

    def get_pending_input(self, user_id, now=None):
        response = self.table.get_item(Key={"pk": _user_pk(user_id), "sk": "PENDING"})
        item = response.get("Item")
        if not item:
            return None
        now = int(time.time() if now is None else now)
        if int(item.get("expires_at", 0)) <= now:
            return None
        return {
            "action": item.get("action"),
            "target_chat_id": int(item["target_chat_id"]),
            "created_at": int(item.get("created_at", 0)),
            "expires_at": int(item.get("expires_at", 0)),
        }

    def delete_pending_input(self, user_id):
        self.table.delete_item(Key={"pk": _user_pk(user_id), "sk": "PENDING"})

    def get_owner_active_chat(self, user_id):
        response = self.table.get_item(
            Key={"pk": _owner_pk(user_id), "sk": "ACTIVE_CHAT"}
        )
        item = response.get("Item") or {}
        chat_id = item.get("chat_id")
        return int(chat_id) if chat_id is not None else None

    def set_owner_active_chat(self, user_id, chat_id):
        self.table.put_item(
            Item={
                "pk": _chat_index_pk(),
                "sk": _chat_index_sk(chat_id),
                "chat_id": int(chat_id),
            }
        )
        self.table.put_item(
            Item={
                "pk": _owner_pk(user_id),
                "sk": "ACTIVE_CHAT",
                "chat_id": int(chat_id),
            }
        )

    def log_usage(self, chat_id, usage, messages_count, ts=None):
        if not usage:
            return
        ts = int(time.time() if ts is None else ts)
        item = {
            "pk": _chat_pk(chat_id),
            "sk": f"USAGE#{ts:020d}#{time.time_ns() % 1_000_000_000:09d}",
            "messages_count": int(messages_count),
            "input_tokens": int(usage.get("input_tokens", 0)),
            "output_tokens": int(usage.get("output_tokens", 0)),
            "total_tokens": int(usage.get("total_tokens", 0)),
            "estimated": bool(usage.get("estimated", True)),
            "model": usage.get("model", ""),
        }
        self.table.put_item(Item=item)

    def usage_totals(self, chat_id, since_ts=None):
        totals = {
            "requests": 0,
            "messages_count": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "estimated_records": 0,
        }
        kwargs = {
            "KeyConditionExpression": "pk = :pk AND begins_with(sk, :prefix)",
            "ExpressionAttributeValues": {
                ":pk": _chat_pk(chat_id),
                ":prefix": "USAGE#",
            },
            "ScanIndexForward": False,
        }
        while True:
            response = self.table.query(**kwargs)
            for item in response.get("Items", []):
                ts = int(item["sk"].removeprefix("USAGE#").split("#", 1)[0])
                if since_ts is not None and ts < int(since_ts):
                    continue
                totals["requests"] += 1
                totals["messages_count"] += int(item.get("messages_count", 0))
                totals["input_tokens"] += int(item.get("input_tokens", 0))
                totals["output_tokens"] += int(item.get("output_tokens", 0))
                totals["total_tokens"] += int(item.get("total_tokens", 0))
                if item.get("estimated", True):
                    totals["estimated_records"] += 1
            if "LastEvaluatedKey" not in response:
                break
            kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        return totals
