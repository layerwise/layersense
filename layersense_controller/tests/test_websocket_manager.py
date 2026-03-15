import json

import pytest

from layersense_controller.websocket_manager import WebSocketManager


class FakeWebSocket:
    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.accepted = False
        self.messages: list[str] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, payload: str) -> None:
        if self.should_fail:
            raise RuntimeError("dead connection")
        self.messages.append(payload)


@pytest.mark.asyncio
async def test_broadcast_sends_to_all_connections() -> None:
    manager = WebSocketManager()
    ws_a = FakeWebSocket()
    ws_b = FakeWebSocket()

    await manager.connect(ws_a)
    await manager.connect(ws_b)

    event = {"type": "scene.updated", "id": "abc123"}
    await manager.broadcast(event)

    expected_payload = json.dumps(event)
    assert ws_a.accepted is True
    assert ws_b.accepted is True
    assert ws_a.messages == [expected_payload]
    assert ws_b.messages == [expected_payload]


@pytest.mark.asyncio
async def test_broadcast_removes_dead_connections() -> None:
    manager = WebSocketManager()
    alive = FakeWebSocket()
    dead = FakeWebSocket(should_fail=True)

    await manager.connect(alive)
    await manager.connect(dead)

    await manager.broadcast({"type": "ping"})

    assert manager._connections == [alive]
