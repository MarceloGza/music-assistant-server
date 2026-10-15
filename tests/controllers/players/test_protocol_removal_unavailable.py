"""Regression coverage for removing temporarily unavailable protocol members."""

import logging
from types import MethodType, SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from music_assistant_models.enums import PlayerFeature, PlayerType

from music_assistant.controllers.players import PlayerController
from music_assistant.models.player import Player


def make_controller(
    *, available: bool, member: bool = True, native: bool = False
) -> tuple[Any, Any, Any]:
    """Build an isolated controller with intercepted protocol commands."""
    child_id = "child"
    child_protocol_id = "sendspin-child"
    parent_protocol_id = "sendspin-parent"
    child_link = SimpleNamespace(
        is_native=False, output_protocol_id=child_protocol_id, available=available
    )
    child = SimpleNamespace(
        player_id=child_id,
        type=PlayerType.PLAYER,
        linked_output_protocols=[child_link],
        get_output_protocol_by_domain=lambda _domain: child_link,
    )
    protocol = SimpleNamespace(
        player_id=parent_protocol_id,
        group_members=[parent_protocol_id, child_protocol_id] if member else [parent_protocol_id],
        provider=SimpleNamespace(domain="sendspin"),
        state=SimpleNamespace(
            name="sendspin-parent", supported_features={PlayerFeature.SET_MEMBERS}
        ),
        synced_to=None,
        set_members=AsyncMock(),
    )
    parent = SimpleNamespace(
        player_id="parent",
        type=PlayerType.PLAYER,
        active_output_protocol=None if native else parent_protocol_id,
        group_members=[child_id] if native else [],
        supported_features={PlayerFeature.SET_MEMBERS} if native else set(),
        state=SimpleNamespace(name="parent", supported_features={PlayerFeature.SET_MEMBERS}),
    )
    parent.set_members = (
        AsyncMock()
        if native
        else lambda **kwargs: Player.set_members(cast("Player", parent), **kwargs)
    )
    players = {
        "parent": parent,
        child_id: child,
        parent_protocol_id: protocol,
        child_protocol_id: SimpleNamespace(provider=SimpleNamespace(domain="sendspin")),
    }
    controller = cast("Any", PlayerController.__new__(PlayerController))
    controller.logger = logging.getLogger(__name__)
    controller.get_player = lambda pid, *_args, **_kwargs: players.get(pid)
    controller._translate_members_for_protocols = lambda _p, _ids, pp, pd: ([], [], pp, pd)
    controller._forward_protocol_set_members = AsyncMock()
    return controller, parent, protocol


@pytest.mark.parametrize("available", [True, False])
async def test_removal_routes_existing_member_even_when_temporarily_unavailable(
    available: bool,
) -> None:
    """Existing membership, not current availability, determines removal routing."""
    controller, parent, protocol = make_controller(available=available)
    await controller._handle_set_members_with_protocols(parent, [], ["child"])
    controller._forward_protocol_set_members.assert_awaited_once_with(
        parent, protocol, [], ["sendspin-child"]
    )


def test_nonmember_is_not_admitted_as_protocol_member() -> None:
    """An unavailable protocol cannot grant membership in an unrelated group."""
    controller, parent, protocol = make_controller(available=False, member=False)
    assert controller._translate_members_to_remove_for_protocols(
        parent, ["child"], protocol, "sendspin"
    ) == ([], ["child"])


async def test_real_native_group_removal_still_uses_native_implementation() -> None:
    """Native-capable players retain their existing removal path."""
    controller, parent, _ = make_controller(available=False, native=True)
    await controller._handle_set_members_with_protocols(parent, [], ["child"])
    parent.set_members.assert_awaited_once_with(
        player_ids_to_add=None, player_ids_to_remove=["child"]
    )
    controller._forward_protocol_set_members.assert_not_awaited()


async def test_unavailable_removal_reaches_real_protocol_forwarder() -> None:
    """Actual forwarding preserves the protocol child identifier and removal-only request."""
    controller, parent, protocol = make_controller(available=False)
    controller._forward_protocol_set_members = MethodType(
        PlayerController._forward_protocol_set_members, controller
    )
    await controller._handle_set_members_with_protocols(parent, [], ["child"])
    protocol.set_members.assert_awaited_once_with(
        player_ids_to_add=None, player_ids_to_remove=["sendspin-child"]
    )
