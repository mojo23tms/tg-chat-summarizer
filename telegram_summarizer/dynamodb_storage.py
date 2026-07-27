import time

from . import config
from .retrieval import rank_memory_snapshots


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


def _message_range_start(ts):
    return f"MSG#{int(ts):020d}#"


def _message_range_end(ts):
    return f"MSG#{int(ts):020d}#\uffff"


def _quota_warning_sk(provider, day):
    return f"QUOTA_WARN#{provider}#{day}"


def _memory_sk(start_ts, end_ts):
    return f"MEMORY#{int(start_ts):020d}#{int(end_ts):020d}"


def _backfill_sk(job_name):
    return f"BACKFILL#{str(job_name).upper()}"


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

    def message_page(
        self,
        chat_id,
        *,
        start_ts=0,
        end_ts=99_999_999_999,
        limit=100,
        exclusive_start_key=None,
    ):
        start_ts = int(start_ts)
        end_ts = int(end_ts)
        limit = int(limit)
        if start_ts > end_ts:
            return [], None
        if limit < 1:
            raise ValueError("limit must be positive")

        kwargs = {
            "KeyConditionExpression": "pk = :pk AND sk BETWEEN :start AND :end",
            "ExpressionAttributeValues": {
                ":pk": _chat_pk(chat_id),
                ":start": _message_range_start(start_ts),
                ":end": _message_range_end(end_ts),
            },
            "ScanIndexForward": False,
            "Limit": limit,
        }
        if exclusive_start_key is not None:
            kwargs["ExclusiveStartKey"] = exclusive_start_key
        response = self.table.query(**kwargs)
        rows = [
            {
                "msg_id": int(item.get("msg_id", 0)),
                "user_id": int(item.get("user_id", 0)),
                "user_name": item.get("user_name", "unknown"),
                "text": item.get("text", ""),
                "ts": int(item.get("ts", 0)),
            }
            for item in response.get("Items", [])
        ]
        return rows, response.get("LastEvaluatedKey")

    def chronological_message_page(
        self,
        chat_id,
        *,
        start_ts=0,
        end_ts=99_999_999_999,
        limit=100,
        exclusive_start_key=None,
    ):
        start_ts = int(start_ts)
        end_ts = int(end_ts)
        limit = int(limit)
        if start_ts > end_ts:
            return [], None
        if limit < 1:
            raise ValueError("limit must be positive")
        kwargs = {
            "KeyConditionExpression": "pk = :pk AND sk BETWEEN :start AND :end",
            "ExpressionAttributeValues": {
                ":pk": _chat_pk(chat_id),
                ":start": _message_range_start(start_ts),
                ":end": _message_range_end(end_ts),
            },
            "ScanIndexForward": True,
            "Limit": limit,
        }
        if exclusive_start_key is not None:
            kwargs["ExclusiveStartKey"] = exclusive_start_key
        response = self.table.query(**kwargs)
        rows = [
            {
                "msg_id": int(item.get("msg_id", 0)),
                "user_id": int(item.get("user_id", 0)),
                "user_name": item.get("user_name", "unknown"),
                "text": item.get("text", ""),
                "ts": int(item.get("ts", 0)),
            }
            for item in response.get("Items", [])
        ]
        return rows, response.get("LastEvaluatedKey")

    def message_cursor(self, chat_id, message):
        return {
            "pk": _chat_pk(chat_id),
            "sk": _message_sk(message["ts"], message["msg_id"]),
        }

    def save_memory_snapshot(self, chat_id, snapshot):
        item = {
            "pk": _chat_pk(chat_id),
            "sk": _memory_sk(snapshot["start_ts"], snapshot["end_ts"]),
            **snapshot,
        }
        self.table.put_item(Item=item)

    def memory_page(
        self,
        chat_id,
        *,
        limit=100,
        exclusive_start_key=None,
    ):
        limit = int(limit)
        if limit < 1:
            raise ValueError("limit must be positive")
        kwargs = {
            "KeyConditionExpression": "pk = :pk AND begins_with(sk, :prefix)",
            "ExpressionAttributeValues": {
                ":pk": _chat_pk(chat_id),
                ":prefix": "MEMORY#",
            },
            "ScanIndexForward": True,
            "Limit": limit,
        }
        if exclusive_start_key is not None:
            kwargs["ExclusiveStartKey"] = exclusive_start_key
        response = self.table.query(**kwargs)
        memories = []
        for item in response.get("Items", []):
            memory = dict(item)
            memory.pop("pk", None)
            memory.pop("sk", None)
            memories.append(memory)
        return memories, response.get("LastEvaluatedKey")

    def search_memories(
        self, chat_id, query="", limit=5, scan_limit=50, start_ts=None, end_ts=None
    ):
        limit = int(limit)
        scan_limit = int(scan_limit)
        if limit < 1 or scan_limit < 1:
            raise ValueError("memory limits must be positive")
        memories = []
        scanned = 0
        cursor = None
        while scanned < scan_limit:
            response = self.table.query(
                KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
                ExpressionAttributeValues={
                    ":pk": _chat_pk(chat_id),
                    ":prefix": "MEMORY#",
                },
                ScanIndexForward=False,
                Limit=min(100, scan_limit - scanned),
                **({"ExclusiveStartKey": cursor} if cursor is not None else {}),
            )
            items = response.get("Items", [])
            scanned += len(items)
            for item in items:
                memory = dict(item)
                memory.pop("pk", None)
                memory.pop("sk", None)
                if start_ts is not None and int(memory.get("end_ts", 0)) < int(start_ts):
                    continue
                if end_ts is not None and int(memory.get("start_ts", 0)) > int(end_ts):
                    continue
                memories.append(memory)
            cursor = response.get("LastEvaluatedKey")
            if cursor is None or not items:
                break
        return rank_memory_snapshots(memories, query, limit)

    def get_backfill_checkpoint(self, chat_id, job_name="historical_memory"):
        response = self.table.get_item(
            Key={"pk": _chat_pk(chat_id), "sk": _backfill_sk(job_name)}
        )
        item = response.get("Item")
        if not item:
            return None
        checkpoint = dict(item)
        checkpoint.pop("pk", None)
        checkpoint.pop("sk", None)
        for key in (
            "start_ts",
            "end_ts",
            "processed_messages",
            "processed_chunks",
            "updated_at",
        ):
            if key in checkpoint:
                checkpoint[key] = int(checkpoint[key])
        return checkpoint

    def save_backfill_checkpoint(
        self, chat_id, checkpoint, job_name="historical_memory"
    ):
        self.table.put_item(
            Item={
                "pk": _chat_pk(chat_id),
                "sk": _backfill_sk(job_name),
                **checkpoint,
            }
        )

    def clear_backfill_checkpoint(self, chat_id, job_name="historical_memory"):
        self.table.delete_item(
            Key={"pk": _chat_pk(chat_id), "sk": _backfill_sk(job_name)}
        )

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
            "provider": usage.get("provider", ""),
            "model": usage.get("model", ""),
        }
        self.table.put_item(Item=item)

    def usage_totals(self, chat_id, since_ts=None, provider=None, model=None):
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
                if provider is not None and item.get("provider", "") != provider:
                    continue
                if model is not None and item.get("model", "") != model:
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

    def quota_warning_sent(self, chat_id, provider, day):
        response = self.table.get_item(
            Key={"pk": _chat_pk(chat_id), "sk": _quota_warning_sk(provider, day)}
        )
        return "Item" in response

    def mark_quota_warning_sent(self, chat_id, provider, day, ts=None):
        ts = int(time.time() if ts is None else ts)
        self.table.put_item(
            Item={
                "pk": _chat_pk(chat_id),
                "sk": _quota_warning_sk(provider, day),
                "provider": provider,
                "day": day,
                "ts": ts,
                "expires_at": ts + 14 * 86400,
            }
        )
