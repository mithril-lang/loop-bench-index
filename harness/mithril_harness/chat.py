"""Direct OpenRouter chat transport (`BENCH_TRANSPORT=chat`).

Measured 2026-09-25 against openai/gpt-6-luna via OpenRouter: provider prompt
caching is hit per *message*, not per token prefix. An append-only message
array reused 99% of the prompt from the second call on, at about 1/10 of the
uncached price. A growing single message was never reused, and sending
`prompt_cache_key` disabled reuse entirely. So this transport sends no tools
and no cache key. The loop builds messages so that everything before the last
message is identical to the previous call.

Usage files use the Hermes field names, so existing summarizers read them:
`input_tokens` is uncached prompt tokens, `cache_read_tokens` is cached prompt
tokens, and `estimated_cost_usd` is the provider-reported cost.
"""

import asyncio
import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ENDPOINT = 'https://openrouter.ai/api/v1/chat/completions'
RETRYABLE = {408, 409, 425, 429, 500, 502, 503, 504}


def openrouter_key():
    key = os.environ.get('OPENROUTER_API_KEY')
    if key:
        return key
    env = Path(os.environ.get('HERMES_ENV_FILE', Path.home() / '.hermes' / '.env'))
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith('OPENROUTER_API_KEY='):
                return line.split('=', 1)[1].strip().strip('"\'')
    raise RuntimeError('OPENROUTER_API_KEY is not set and not in the Hermes env file')


def _post(body, key, timeout):
    request = urllib.request.Request(ENDPOINT, data=json.dumps(body).encode(), method='POST',
                                     headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


MAX_OUTPUT_TOKENS = int(os.environ.get('BENCH_MAX_OUTPUT_TOKENS', '16384'))
REQUEST_DEADLINE = int(os.environ.get('BENCH_REQUEST_DEADLINE', '240'))


class DeadlineExceeded(Exception):
    pass


async def call_with_deadline(fn, *args, deadline):
    """Run a blocking call in a daemon thread and stop waiting after `deadline`
    seconds of wall time. A socket read timeout does not bound a request whose
    server keeps sending bytes: two requests ran 401 s and 475 s past a 120 s
    read timeout (both hit the 65,536-token output limit). The abandoned
    thread is a daemon, so it cannot hold the process open at exit."""
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    def run():
        # Wrapped, not raised into the future: a TimeoutError from the socket must
        # stay distinguishable from our own deadline (asyncio.TimeoutError is the
        # builtin TimeoutError since Python 3.11).
        try:
            outcome = ('ok', fn(*args))
        except BaseException as exc:
            outcome = ('error', exc)
        loop.call_soon_threadsafe(lambda o=outcome: future.done() or future.set_result(o))

    threading.Thread(target=run, daemon=True).start()
    try:
        kind, value = await asyncio.wait_for(asyncio.shield(future), deadline)
    except asyncio.TimeoutError:
        raise DeadlineExceeded(f'no response within {deadline} s')
    if kind == 'error':
        raise value
    return value


def usage_record(result, wall):
    u = result.get('usage') or {}
    prompt = u.get('prompt_tokens') or 0
    cached = (u.get('prompt_tokens_details') or {}).get('cached_tokens') or 0
    completion = u.get('completion_tokens') or 0
    return {'transport': 'chat', 'model': result.get('model'), 'provider': result.get('provider'),
            'input_tokens': prompt - cached, 'cache_read_tokens': cached, 'cache_write_tokens': 0,
            'output_tokens': completion,
            'reasoning_tokens': (u.get('completion_tokens_details') or {}).get('reasoning_tokens') or 0,
            'total_tokens': prompt + completion, 'estimated_cost_usd': u.get('cost'),
            'api_calls': 1, 'completed': True, 'partial': False, 'wall_seconds': round(wall, 3)}


def _failed(usage_path, attempt, record):
    Path(usage_path).with_name(f'{Path(usage_path).stem}-failed-{attempt}.json').write_text(json.dumps(record))


async def chat_complete(messages, usage_path, model=None, reasoning=None,
                        timeout=int(os.environ.get('BENCH_REQUEST_TIMEOUT', '120'))):
    """Returns the assistant text. Writes one usage file per successful call and
    one `-failed-N` file per failed attempt. Retries only transport errors; no
    terminal action has run for this call, so a retry repeats nothing."""
    body = {'model': model or os.environ.get('BENCH_MODEL', 'openai/gpt-6-luna'),
            'reasoning': {'effort': reasoning or os.environ.get('BENCH_REASONING', 'medium')},
            'usage': {'include': True}, 'max_tokens': MAX_OUTPUT_TOKENS, 'messages': messages}
    key = openrouter_key()
    failures = []
    for attempt in range(3):
        if failures and failures[-1].get('status') == 'empty':
            # an identical retry of an empty reply tends to stay empty: add one short note, on a copy
            body = dict(body, messages=list(messages) + [{'role': 'user', 'content':
                    'Your previous reply was empty. Reply now with the requested output only.'}])
        started = time.monotonic()
        try:
            result = await call_with_deadline(_post, body, key, timeout, deadline=REQUEST_DEADLINE)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors='replace')[-600:]
            failures.append({'status': exc.code, 'detail': detail})
            retry = exc.code in RETRYABLE
            _failed(usage_path, attempt, {'transport': 'chat', 'completed': False, 'partial': True, 'status': exc.code,
                                          'wall_seconds': round(time.monotonic() - started, 3), 'estimated_cost_usd': None})
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, DeadlineExceeded) as exc:
            failures.append({'status': None, 'detail': str(exc)[-600:]})
            retry = True
            # tokens and cost of an abandoned request are unknown: recorded as missing, never as zero
            _failed(usage_path, attempt, {'transport': 'chat', 'completed': False, 'partial': True,
                                          'status': type(exc).__name__, 'wall_seconds': round(time.monotonic() - started, 3),
                                          'estimated_cost_usd': None})
        else:
            choice = (result.get('choices') or [{}])[0]
            text = (choice.get('message') or {}).get('content')
            if isinstance(text, str) and text.strip():
                record = usage_record(result, time.monotonic() - started)
                record['finish_reason'] = choice.get('finish_reason')
                Path(usage_path).write_text(json.dumps(record))
                # raw reply, private run data: lets a parse decision be checked afterwards
                Path(usage_path).with_suffix('.reply.txt').write_text(text)
                return text
            failures.append({'status': 'empty', 'detail': json.dumps(choice)[-600:]})
            _failed(usage_path, attempt, dict(usage_record(result, time.monotonic() - started), completed=False, partial=True))
            retry = True
        if not retry or attempt == 2:
            break
        await asyncio.sleep(2 * (attempt + 1))
    raise RuntimeError(f'chat transport failed after {len(failures)} attempt(s): {json.dumps(failures)}')
