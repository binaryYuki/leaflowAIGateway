import json
from typing import List

import pytest
import respx
import httpx

import main

UPSTREAM = main.UPSTREAM_BASE_URL


def _make_transport():
    return httpx.ASGITransport(app=main.app)


@pytest.mark.anyio
async def test_healthz():
    transport = _make_transport()
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/healthz")
        assert r.status_code == 200
        assert r.text == "ok"


@pytest.mark.anyio
async def test_models_requires_auth():
    transport = _make_transport()
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/v1/models")
        assert r.status_code == 401
        assert r.json()["detail"].startswith("Missing API token")


@pytest.mark.anyio
async def test_models_with_auth_and_normalization():
    captured_auth: List[str] = []

    with respx.mock(base_url=UPSTREAM) as router:
        @router.get("/models")
        def _models(request: httpx.Request):
            captured_auth.append(request.headers.get("Authorization", ""))
            return httpx.Response(200, json={"object": "list", "data": ["model-a"]})

        transport = _make_transport()
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get("/v1/models", headers={"Authorization": "Bearer sk-mytesttoken"})
            assert r.status_code == 200
            assert r.json()["data"] == ["model-a"]

    assert captured_auth == ["Bearer mytesttoken"], f"Header not normalized: {captured_auth}"


@pytest.mark.anyio
async def test_fallback_static_api_key(monkeypatch):
    monkeypatch.setattr(main, "STATIC_API_KEY", "sk-fallback123")

    with respx.mock(base_url=UPSTREAM) as router:
        router.get("/models").mock(return_value=httpx.Response(200, json={"object": "list", "data": []}))
        transport = _make_transport()
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get("/v1/models")
            assert r.status_code == 200
            assert r.json()["data"] == []


@pytest.mark.anyio
async def test_embeddings_post():
    with respx.mock(base_url=UPSTREAM) as router:
        @router.post("/embeddings")
        def _emb(request: httpx.Request):
            body = json.loads(request.content.decode())
            assert body["input"] == ["hello"]
            return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})

        transport = _make_transport()
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post("/v1/embeddings", headers={"Authorization": "Bearer token123"}, json={"input": ["hello"]})
            assert r.status_code == 200
            assert r.json()["data"][0]["embedding"] == [0.1, 0.2]


@pytest.mark.anyio
async def test_chat_completions_non_stream():
    with respx.mock(base_url=UPSTREAM) as router:
        @router.post("/chat/completions")
        def _chat(request: httpx.Request):
            body = json.loads(request.content.decode())
            assert body["stream"] is False
            return httpx.Response(200, json={"id": "1", "choices": [{"message": {"content": "Hi"}}]})

        transport = _make_transport()
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/v1/chat/completions",
                headers={"Authorization": "Bearer token123"},
                json={"messages": [{"role": "user", "content": "Hello"}], "stream": False},
            )
            assert r.status_code == 200
            assert r.json()["choices"][0]["message"]["content"] == "Hi"


@pytest.mark.anyio
async def test_chat_completions_streaming():
    chunks = [b"data: {\"id\":\"1\",\"object\":\"chunk\"}\n\n", b"data: [DONE]\n\n"]

    async def stream_side_effect(request: httpx.Request):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=b"".join(chunks))

    with respx.mock(base_url=UPSTREAM) as router:
        router.post("/chat/completions").mock(side_effect=stream_side_effect)

        transport = _make_transport()
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            async with client.stream(
                "POST",
                "/v1/chat/completions",
                headers={"Authorization": "Bearer token123"},
                json={"messages": [{"role": "user", "content": "Hello"}], "stream": True},
            ) as resp:
                assert resp.status_code == 200
                body = b"".join([chunk async for chunk in resp.aiter_raw()])
                for c in chunks:
                    assert c in body


@pytest.mark.anyio
async def test_catch_all_generic():
    with respx.mock(base_url=UPSTREAM) as router:
        router.get("/other").mock(return_value=httpx.Response(200, json={"ok": True}))
        transport = _make_transport()
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get("/v1/other", headers={"Authorization": "Bearer token123"})
            assert r.status_code == 200
            assert r.json() == {"ok": True}


@pytest.mark.anyio
async def test_catch_all_passes_query():
    with respx.mock(base_url=UPSTREAM) as router:
        @router.get("/search")
        def _search(request: httpx.Request):
            assert request.url.params.get("q") == "abc"
            return httpx.Response(200, json={"results": 1})

        transport = _make_transport()
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get("/v1/search?q=abc", headers={"Authorization": "Bearer token123"})
            assert r.status_code == 200
            assert r.json()["results"] == 1
