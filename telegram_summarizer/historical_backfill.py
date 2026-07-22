import time

from . import config
from . import llm
from . import memory


JOB_NAME = "historical_memory"


class BackfillConfigurationError(ValueError):
    pass


def _validated_limits(chunk_size, max_messages, max_input_tokens, output_tokens):
    values = {
        "chunk_size": int(chunk_size),
        "max_messages": int(max_messages),
        "max_input_tokens": int(max_input_tokens),
        "output_tokens": int(output_tokens),
    }
    if not 1 <= values["chunk_size"] <= 500:
        raise BackfillConfigurationError("chunk_size must be between 1 and 500")
    for key in ("max_messages", "max_input_tokens", "output_tokens"):
        if values[key] < 1:
            raise BackfillConfigurationError(f"{key} must be positive")
    if values["output_tokens"] >= values["max_input_tokens"]:
        raise BackfillConfigurationError(
            "output_tokens must be smaller than max_input_tokens"
        )
    return values


def _settings_for_run(storage, chat_id, provider=None, model=None):
    settings = storage.get_settings(chat_id)
    if provider:
        settings["provider"] = llm.normalize_provider(provider)
    if model:
        settings["model"] = str(model).strip()
    resolved_provider, resolved_model = llm.resolve_provider_model(settings)
    settings["provider"] = resolved_provider
    settings["model"] = resolved_model
    return settings


def _checkpoint_for_run(storage, chat_id, start_ts, end_ts):
    checkpoint = storage.get_backfill_checkpoint(chat_id, job_name=JOB_NAME)
    if not checkpoint:
        return None
    if int(checkpoint.get("start_ts", start_ts)) != start_ts or int(
        checkpoint.get("end_ts", end_ts)
    ) != end_ts:
        raise BackfillConfigurationError(
            "existing checkpoint uses a different time range; reset it explicitly"
        )
    return checkpoint


def run_backfill(
    storage,
    chat_id,
    *,
    chunk_size=250,
    max_messages=5000,
    start_ts=0,
    end_ts=99_999_999_999,
    max_input_tokens=12000,
    output_tokens=800,
    provider=None,
    model=None,
    input_cost_per_million=0.0,
    output_cost_per_million=0.0,
    max_estimated_cost=None,
    dry_run=False,
    backend_fn=None,
    now_fn=None,
):
    limits = _validated_limits(
        chunk_size, max_messages, max_input_tokens, output_tokens
    )
    chat_id = int(chat_id)
    start_ts = int(start_ts)
    end_ts = int(end_ts)
    if start_ts > end_ts:
        raise BackfillConfigurationError("start_ts must not exceed end_ts")
    if float(input_cost_per_million) < 0 or float(output_cost_per_million) < 0:
        raise BackfillConfigurationError("cost rates must not be negative")
    if max_estimated_cost is not None:
        max_estimated_cost = float(max_estimated_cost)
        if max_estimated_cost < 0:
            raise BackfillConfigurationError("max_estimated_cost must not be negative")
        if not float(input_cost_per_million) and not float(output_cost_per_million):
            raise BackfillConfigurationError(
                "cost rates are required when max_estimated_cost is set"
            )
    now_fn = now_fn or time.time
    settings = _settings_for_run(storage, chat_id, provider=provider, model=model)
    checkpoint = _checkpoint_for_run(storage, chat_id, start_ts, end_ts)
    cursor = checkpoint.get("cursor") if checkpoint else None
    previous_messages = int((checkpoint or {}).get("processed_messages", 0))
    previous_chunks = int((checkpoint or {}).get("processed_chunks", 0))
    run_messages = 0
    run_chunks = 0
    estimated_input_tokens = 0
    actual_input_tokens = 0
    actual_output_tokens = 0
    oversized_chunks = 0
    complete = False

    while run_messages < limits["max_messages"]:
        page_limit = min(
            limits["chunk_size"], limits["max_messages"] - run_messages
        )
        messages, next_cursor = storage.chronological_message_page(
            chat_id,
            start_ts=start_ts,
            end_ts=end_ts,
            limit=page_limit,
            exclusive_start_key=cursor,
        )
        if not messages:
            complete = True
            break
        selected = llm.select_memory_messages_for_token_budget(
            messages,
            settings,
            max_input_tokens=limits["max_input_tokens"],
            output_tokens=limits["output_tokens"],
        )
        prompt_tokens = llm.estimate_tokens(llm.build_memory_prompt(messages, settings))
        estimated_input_tokens += prompt_tokens
        projected_cost = (
            estimated_input_tokens * float(input_cost_per_million)
            + (run_chunks + 1)
            * limits["output_tokens"]
            * float(output_cost_per_million)
        ) / 1_000_000
        if (
            not dry_run
            and max_estimated_cost is not None
            and projected_cost > max_estimated_cost
        ):
            raise BackfillConfigurationError(
                "next chunk would exceed --max-estimated-cost; checkpoint was not advanced"
            )
        if len(selected) != len(messages):
            oversized_chunks += 1
            if not dry_run:
                raise BackfillConfigurationError(
                    "a chunk exceeds the token budget; reduce --chunk-size or "
                    "increase --max-input-tokens"
                )
        if not dry_run:
            result = memory.generate_snapshot_from_messages(
                chat_id,
                storage,
                settings,
                messages,
                backend_fn=backend_fn,
                now_fn=now_fn,
                max_input_tokens=limits["max_input_tokens"],
                output_tokens=limits["output_tokens"],
            )
            usage = result.get("usage")
            if usage:
                actual_input_tokens += int(usage.get("input_tokens", 0))
                actual_output_tokens += int(usage.get("output_tokens", 0))
                storage.log_usage(
                    chat_id,
                    usage,
                    int(result.get("source_message_count", len(messages))),
                    ts=int(now_fn()),
                )
            if result.get("invalid_memory"):
                raise ValueError(
                    "provider returned invalid memory JSON; checkpoint was not advanced"
                )

        run_messages += len(messages)
        run_chunks += 1
        cursor = (
            next_cursor
            if next_cursor is not None
            else storage.message_cursor(chat_id, messages[-1])
        )
        complete = next_cursor is None
        if not dry_run:
            saved_checkpoint = {
                "version": 1,
                "status": "complete" if complete else "in_progress",
                "start_ts": start_ts,
                "end_ts": end_ts,
                "cursor": cursor,
                "processed_messages": previous_messages + run_messages,
                "processed_chunks": previous_chunks + run_chunks,
                "provider": settings["provider"],
                "model": settings["model"],
                "updated_at": int(now_fn()),
            }
            storage.save_backfill_checkpoint(
                chat_id, saved_checkpoint, job_name=JOB_NAME
            )
        if complete:
            break

    estimated_output_tokens = run_chunks * limits["output_tokens"]
    estimated_cost = (
        estimated_input_tokens * float(input_cost_per_million)
        + estimated_output_tokens * float(output_cost_per_million)
    ) / 1_000_000
    quota = int(config.DAILY_TOKEN_QUOTAS.get(settings["provider"], 0))
    quota_total_tokens = actual_input_tokens + actual_output_tokens
    if quota and hasattr(storage, "usage_totals"):
        day_start = int(now_fn()) // 86400 * 86400
        totals = storage.usage_totals(
            chat_id,
            since_ts=day_start,
            provider=settings["provider"],
            model=settings["model"],
        )
        quota_total_tokens = int(totals.get("total_tokens", quota_total_tokens))
    quota_warning = bool(
        quota
        and quota_total_tokens
        >= quota * (100 - int(config.QUOTA_WARNING_REMAINING_PERCENT)) / 100
    )
    return {
        "status": "complete" if complete else "in_progress",
        "dry_run": bool(dry_run),
        "processed_messages": run_messages,
        "processed_chunks": run_chunks,
        "total_processed_messages": previous_messages + run_messages,
        "total_processed_chunks": previous_chunks + run_chunks,
        "estimated_input_tokens": estimated_input_tokens,
        "estimated_output_tokens": estimated_output_tokens,
        "estimated_cost": estimated_cost,
        "actual_input_tokens": actual_input_tokens,
        "actual_output_tokens": actual_output_tokens,
        "configured_daily_quota": quota,
        "quota_total_tokens": quota_total_tokens,
        "quota_warning": quota_warning,
        "oversized_chunks": oversized_chunks,
        "provider": settings["provider"],
        "model": settings["model"],
    }
