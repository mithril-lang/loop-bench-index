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
            'usage': {'include': True}, 'messages': messages}
    key = openrouter_key()
    failures = []
    for attempt in range(3):
        started = time.monotonic()
        try:
            result = await asyncio.to_thread(_post, body, key, timeout)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors='replace')[-600:]
            failures.append({'status': exc.code, 'detail': detail})
            retry = exc.code in RETRYABLE
            _failed(usage_path, attempt, {'transport': 'chat', 'completed': False, 'partial': True, 'status': exc.code,
                                          'wall_seconds': round(time.monotonic() - started, 3), 'estimated_cost_usd': None})
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
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
                Path(usage_path).write_text(json.dumps(usage_record(result, time.monotonic() - started)))
                return text
            failures.append({'status': 'empty', 'detail': json.dumps(choice)[-600:]})
            _failed(usage_path, attempt, dict(usage_record(result, time.monotonic() - started), completed=False, partial=True))
            retry = True
        if not retry or attempt == 2:
            break
        await asyncio.sleep(2 * (attempt + 1))
    raise RuntimeError(f'chat transport failed after {len(failures)} attempt(s): {json.dumps(failures)}')
