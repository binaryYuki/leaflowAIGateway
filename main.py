from __future__ import annotations

import os
import json
from typing import AsyncIterator, Dict, Any, Optional

import httpx
from fastapi import FastAPI, Request, Response, Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware

UPSTREAM_BASE_URL = os.getenv("UPSTREAM_BASE_URL", "http://llm.ai-infra.svc.cluster.local/v1")
# If set, this key will be used when the incoming request has no Authorization header.
STATIC_API_KEY = os.getenv("STATIC_API_KEY")

# Tuning knobs
CONNECT_TIMEOUT = float(os.getenv("CONNECT_TIMEOUT", "5"))
READ_TIMEOUT = float(os.getenv("READ_TIMEOUT", "600"))  # allow long streams
MAX_KEEPALIVE = int(os.getenv("MAX_KEEPALIVE", "100"))
MAX_CONNECTIONS = int(os.getenv("MAX_CONNECTIONS", "200"))
RETRY_TIMES = int(os.getenv("RETRY_TIMES", "2"))

app = FastAPI(title="Leaflow LLM FastAPI Proxy", version="1.0.0")

# CORS: adjust as needed
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

client: Optional[httpx.AsyncClient] = None


def _normalize_key(raw: str) -> str:
    """Accept either plain token or sk- prefixed token.

    Examples:
      - ey1234.ABC.456 => ey1234.ABC.456
      - sk-ey1234.ABC.456 => ey1234.ABC.456
    """
    if not raw:
        return raw
    if raw.startswith("Bearer "):
        raw = raw[len("Bearer "):]
    if raw.startswith("sk-"):
        return raw[3:]
    return raw


async def _build_auth_header() -> Dict[str, str]:
    token = _normalize_key(STATIC_API_KEY)

    if not token:
        # Upstream requires a token
        raise HTTPException(status_code=401, detail="Missing API token. Supply Authorization: Bearer <token>.")

    return {"Authorization": f"Bearer {token}"}


@app.on_event("startup")
async def _startup() -> None:
    global client
    limits = httpx.Limits(max_keepalive_connections=MAX_KEEPALIVE, max_connections=MAX_CONNECTIONS)
    timeout = httpx.Timeout(
        connect=CONNECT_TIMEOUT,
        read=READ_TIMEOUT,
        write=READ_TIMEOUT,
        pool=CONNECT_TIMEOUT,
    )
    client = httpx.AsyncClient(base_url=UPSTREAM_BASE_URL, http2=True, limits=limits, timeout=timeout)


@app.on_event("shutdown")
async def _shutdown() -> None:
    global client
    if client:
        await client.aclose()
        client = None


@app.middleware("http")
async def API_KEY_auth(request: Request, call_next):
    """
    Simple middleware to enforce presence of a valid API key in the Authorization header.
    If STATIC_API_KEY is set, it will be used as a fallback if the incoming request has no Authorization header.
    1. If neither is present, return 401.
    2. If the key is present but invalid, return 403.
    3. If valid, proceed to the requested endpoint.
    4. If STATIC_API_KEY is set, it will be used as a fallback if the incoming request has no Authorization header.
    :param request:
    :param call_next:
    :return:
    """
    # 生成 request ID（加到 response header）
    request_id = "ns3::" + os.urandom(16).hex()

    # 获取 Authorization
    key = request.headers.get("Authorization")
    if key:
        key = key.replace("Bearer ", "").strip()
    elif STATIC_API_KEY:
        key = STATIC_API_KEY
    else:
        return JSONResponse(
            status_code=401,
            content={"detail": "Missing API token. Supply Authorization header and try again."},
            headers={"Content-Type": "application/json", "X-Request-ID": request_id}
        )

    if key != os.environ.get('SERVICE_API_KEY'):
        return JSONResponse(status_code=403, content={"detail": "Invalid API token."}, headers={"X-Request-ID": request_id})

    # 继续处理请求
    response = await call_next(request)

    # 给 response 添加 request-id header
    response.headers["x-request-id"] = request_id
    return response


async def _retry_request(method: str, url: str, *, headers: Dict[str, str], json_body: Any | None = None,
                         params: Dict[str, Any] | None = None) -> httpx.Response:
    assert client is not None
    last_exc: Optional[Exception] = None
    for attempt in range(RETRY_TIMES + 1):
        try:
            resp = await client.request(method, url, headers=headers, json=json_body, params=params)
            return resp
        except (httpx.ConnectError, httpx.ReadTimeout) as e:
            last_exc = e
            if attempt >= RETRY_TIMES:
                break
    # Exhausted retries
    raise HTTPException(status_code=504, detail=f"Upstream request failed: {last_exc}")


async def _proxy_stream_post(path: str, *, headers: Dict[str, str], body: Dict[str, Any]) -> StreamingResponse:
    assert client is not None

    # Ensure stream flag is preserved (default False if absent)
    stream = bool(body.get("stream", False))

    # Use streaming mode only if client asked for it
    if not stream:
        # Non-streaming: just forward and return JSON
        resp = await _retry_request("POST", path, headers=headers, json_body=body)
        content_type = resp.headers.get("content-type", "application/json")
        if resp.status_code >= 400:
            # Pass through upstream error payload
            return StreamingResponse(iter([resp.content]), status_code=resp.status_code, media_type=content_type)
        return StreamingResponse(iter([resp.content]), media_type=content_type)

    # Streaming path
    try:
        async with client.stream("POST", path, headers=headers, json=body) as upstream:
            # Propagate status and headers sensibly
            media_type = upstream.headers.get("content-type", "text/event-stream")

            async def event_iterator() -> AsyncIterator[bytes]:
                async for chunk in upstream.aiter_raw():
                    # pass through chunks as-is (SSE or chunked JSON)
                    yield chunk

            return StreamingResponse(event_iterator(), status_code=upstream.status_code, media_type=media_type)
    except (httpx.ConnectError, httpx.ReadTimeout) as e:
        raise HTTPException(status_code=504, detail=f"Upstream stream failed: {e}")


@app.get("/healthz")
async def healthz() -> PlainTextResponse:
    return PlainTextResponse("ok")


@app.get("/v1/models")
async def list_models(authorization: Optional[str] = Header(default=None, convert_underscores=False)) -> Response:
    headers = await _build_auth_header()
    resp = await _retry_request("GET", "/models", headers=headers)
    try:
        data = resp.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="Bad upstream response (non-JSON)")
    return JSONResponse(status_code=resp.status_code, content=data)


@app.post("/v1/embeddings")
async def embeddings(request: Request,
                     authorization: Optional[str] = Header(default=None, convert_underscores=False)) -> Response:
    body = await request.json()
    headers = await _build_auth_header()
    resp = await _retry_request("POST", "/embeddings", headers=headers, json_body=body)
    # Pass through JSON or error JSON
    try:
        data = resp.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="Bad upstream response (non-JSON)")
    return JSONResponse(status_code=resp.status_code, content=data)


@app.post("/v1/chat/completions")
async def chat_completions(request: Request,
                           authorization: Optional[str] = Header(default=None, convert_underscores=False)) -> Response:
    """
    Proxy /v1/chat/completions with special handling for streaming.
    :param request:
    :param authorization:
    :return:
    """
    body = await request.json()
    headers = await _build_auth_header()
    return await _proxy_stream_post("/chat/completions", headers=headers, body=body)


# Optional: a generic passthrough if you want to support future endpoints without code changes
@app.api_route("/v1/{rest_of_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def catch_all_v1(request: Request, rest_of_path: str,
                       authorization: Optional[str] = Header(default=None, convert_underscores=False)) -> Response:
    """
    A catch-all proxy for any other /v1/* paths not explicitly handled above.
    :param request:
    :param rest_of_path:
    :param authorization:
    :return:
    """
    # Avoid double-handling known routes
    if rest_of_path in {"chat/completions", "embeddings", "models"}:
        raise HTTPException(status_code=405, detail="Method not allowed for this path (handled elsewhere)")

    headers = await _build_auth_header()

    # Build upstream URL
    upstream_path = f"/{rest_of_path}"

    # Prepare request parts
    method = request.method
    params = dict(request.query_params)

    # Read body safely (may be empty)
    try:
        raw_body = await request.body()
        json_body = json.loads(raw_body) if raw_body else None
    except json.JSONDecodeError:
        json_body = None

    # Forward
    resp = await _retry_request(method, f"/{rest_of_path}", headers=headers, json_body=json_body, params=params)

    # Try to keep content-type
    content_type = resp.headers.get("content-type") or "application/octet-stream"
    return Response(status_code=resp.status_code, content=resp.content, media_type=content_type)


if __name__ == "__main__":
    # check compulsory env vars
    compulsory_vars = ["UPSTREAM_BASE_URL", "STATIC_API_KEY", "SERVICE_API_KEY"]
    for var in compulsory_vars:
        if not os.getenv(var):
            raise RuntimeError(f"Environment variable {var} must be set")
    print("Starting Leaflet")

    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
