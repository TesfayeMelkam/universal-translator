"""A tiny stand-in for FastAPI/pydantic/starlette, used ONLY when the real packages are not installed
(for example in a sandbox without internet). It lets tests/test_glue.py run the real route functions in
ai_services/main.py: dependencies, headers, query/body parsing, cookies, error handlers, WebSocket handler.
It is NOT FastAPI: when the real FastAPI is installed these tests are skipped and tests/test_api.py runs instead."""
import asyncio
import inspect
import json
import re
import sys
import types
import typing

_REQ = object()


class _Dep:
    def __init__(self, dependency=None):
        self.dependency = dependency


def Depends(dependency=None):
    return _Dep(dependency)


class _HeaderDefault:
    def __init__(self, default):
        self.default = default


def Header(default=None, **_):
    return _HeaderDefault(default)


class _FieldInfo:
    def __init__(self, default, factory):
        self.default, self.factory = default, factory


def Field(default=_REQ, *, default_factory=None, **_):
    return _FieldInfo(default, default_factory)


class ValidationError(ValueError):
    pass


class BaseModel:
    def __init__(self, **data):
        for name in typing.get_type_hints(type(self)):
            if name in data:
                value = data[name]
            else:
                d = getattr(type(self), name, _REQ)
                if isinstance(d, _FieldInfo):
                    if d.factory:
                        value = d.factory()
                    elif d.default is not _REQ:
                        value = d.default
                    else:
                        raise ValidationError(name)
                elif d is _REQ:
                    raise ValidationError(name)
                else:
                    value = d
            setattr(self, name, value)


class _Headers(dict):
    def __init__(self, data=None):
        super().__init__({k.lower(): v for k, v in (data or {}).items()})

    def get(self, key, default=None):
        return super().get(key.lower(), default)


class Request:
    def __init__(self, method="GET", path="/", headers=None, cookies=None, body=b"", client="1.2.3.4", scheme="http"):
        self.method, self.headers, self.cookies, self._body = method, _Headers(headers), dict(cookies or {}), body
        self.client = types.SimpleNamespace(host=client)
        self.url = types.SimpleNamespace(scheme=scheme, path=path)

    async def body(self):
        return self._body

    async def json(self):
        return json.loads(self._body)


class Response:
    def __init__(self, content=b"", status_code=200, headers=None, media_type=None):
        self.content, self.status_code, self.headers, self.media_type = content, status_code, dict(headers or {}), media_type
        self.cookies, self.deleted = {}, []

    def set_cookie(self, key, value="", **kw):
        self.cookies[key] = (value, kw)

    def delete_cookie(self, key, **_):
        self.deleted.append(key)


class JSONResponse(Response):
    def __init__(self, content, status_code=200, headers=None):
        super().__init__(json.dumps(content).encode(), status_code, headers, "application/json")


class FileResponse(Response):
    def __init__(self, path, media_type=None, **_):
        super().__init__(b"", 200, None, media_type)
        self.path = path


class WebSocketDisconnect(Exception):
    pass


class WebSocket:
    def __init__(self, headers=None):
        self.headers, self.inbox, self.sent, self.closed, self.accepted = _Headers(headers), asyncio.Queue(), [], None, False

    async def accept(self):
        self.accepted = True

    async def receive_text(self):
        item = await self.inbox.get()
        if item is None:
            raise WebSocketDisconnect()
        return item

    async def send_json(self, data):
        self.sent.append(data)

    async def close(self, code=1000):
        self.closed = code

    def push(self, obj):
        self.inbox.put_nowait(obj if isinstance(obj, str) else json.dumps(obj))

    def hang_up(self):
        self.inbox.put_nowait(None)


class FastAPI:
    def __init__(self, **_):
        self.routes, self.ws_routes, self.exception_handlers = [], {}, {}

    def _route(self, method, path, dependencies=None, **_):
        def deco(fn):
            self.routes.append((method, path, fn, dependencies or []))
            return fn
        return deco

    def get(self, path, **kw):
        return self._route("GET", path, **kw)

    def post(self, path, **kw):
        return self._route("POST", path, **kw)

    def delete(self, path, **kw):
        return self._route("DELETE", path, **kw)

    def websocket(self, path):
        def deco(fn):
            self.ws_routes[path] = fn
            return fn
        return deco

    def middleware(self, _kind):
        return lambda fn: fn

    def exception_handler(self, exc):
        def deco(fn):
            self.exception_handlers[exc] = fn
            return fn
        return deco

    def add_middleware(self, *a, **k):
        pass

    def mount(self, *a, **k):
        pass


class Result:
    def __init__(self, resp):
        self.resp, self.status_code, self.content, self.headers = resp, resp.status_code, resp.content, resp.headers

    def json(self):
        return json.loads(self.content)


class Client:
    """Like a browser: remembers cookies between requests."""

    def __init__(self, app):
        self.app, self.cookies = app, {}

    def request(self, method, path, params=None, json_body=None, data=None, headers=None, omit_length=False, origin_host="testserver"):
        body = json.dumps(json_body).encode() if json_body is not None else (data or b"")
        hdrs = {"host": origin_host, **(headers or {})}
        if not omit_length and (data is not None or json_body is not None):
            hdrs["content-length"] = str(len(body))
        req = Request(method, path, hdrs, self.cookies, body)
        resp = asyncio.run(self._dispatch(req, params or {}, json_body))
        for k, (v, _) in resp.cookies.items():
            self.cookies[k] = v
        for k in resp.deleted:
            self.cookies.pop(k, None)
        return Result(resp)

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, **kw):
        return self.request("POST", path, **kw)

    def delete(self, path, **kw):
        return self.request("DELETE", path, **kw)

    async def _dispatch(self, req, query, json_body):
        for method, pattern, fn, deps in self.app.routes:
            names = re.findall(r"{(\w+)}", pattern)
            m = re.fullmatch(re.sub(r"{\w+}", r"([^/]+)", pattern), req.url.path) if names else (req.url.path == pattern and re.match("", ""))
            if method == req.method and m:
                ctx = types.SimpleNamespace(request=req, query=query, json=json_body,
                                            path=dict(zip(names, m.groups())) if names else {})
                try:
                    for d in deps:
                        await self._run(d.dependency, ctx)
                    out = await self._run(fn, ctx)
                except Exception as exc:  # noqa: BLE001
                    for etype, handler in self.app.exception_handlers.items():
                        if isinstance(exc, etype):
                            return await handler(req, exc)
                    if isinstance(exc, (ValidationError, _Unprocessable)):
                        return JSONResponse({"detail": str(exc)}, 422)
                    raise
                return out if isinstance(out, Response) else JSONResponse(out)
        return JSONResponse({"detail": "Not Found"}, 404)

    async def _run(self, fn, ctx):
        try:
            hints = typing.get_type_hints(fn)
        except Exception:  # noqa: BLE001
            hints = {}
        kwargs = {}
        for name, p in inspect.signature(fn).parameters.items():
            ann, d = hints.get(name, p.annotation), p.default
            if isinstance(d, _Dep):
                kwargs[name] = await self._run(d.dependency, ctx)
            elif isinstance(d, _HeaderDefault):
                kwargs[name] = ctx.request.headers.get(name.replace("_", "-"), d.default)
            elif ann is Request:
                kwargs[name] = ctx.request
            elif inspect.isclass(ann) and issubclass(ann, BaseModel):
                kwargs[name] = ann(**(ctx.json or {}))
            elif name in ctx.path:
                kwargs[name] = _cast(ctx.path[name], ann)
            elif name in ctx.query:
                kwargs[name] = _cast(ctx.query[name], ann)
            elif d is not inspect.Parameter.empty:
                kwargs[name] = d
            else:
                raise _Unprocessable(name)
        out = fn(**kwargs)
        return await out if inspect.isawaitable(out) else out


class _Unprocessable(Exception):
    pass


def _cast(value, ann):
    if ann is int:
        return int(value)
    if ann is float:
        return float(value)
    if ann is bool:
        return str(value).lower() in ("1", "true", "yes")
    return value


def install():
    """Register the stand-in modules (call only when the real FastAPI is not installed)."""
    def mod(name, **attrs):
        m = types.ModuleType(name)
        m.__path__ = []
        m.__dict__.update(attrs)
        sys.modules[name] = m
        return m
    mod("fastapi", FastAPI=FastAPI, Depends=Depends, Header=Header, Request=Request, WebSocket=WebSocket,
        WebSocketDisconnect=WebSocketDisconnect)
    mod("fastapi.middleware")
    mod("fastapi.middleware.cors", CORSMiddleware=type("CORSMiddleware", (), {}))
    mod("fastapi.responses", FileResponse=FileResponse, JSONResponse=JSONResponse, Response=Response)
    mod("fastapi.staticfiles", StaticFiles=type("StaticFiles", (), {"__init__": lambda self, **k: None}))
    mod("starlette")
    mod("starlette.concurrency", run_in_threadpool=lambda fn, *a, **k: asyncio.to_thread(fn, *a, **k))
    mod("pydantic", BaseModel=BaseModel, Field=Field)
