"""
channel factory
"""
from .channel import Channel


def create_channel(channel_type, instance_id="", bound_agent_id="", credentials=None, members=None) -> Channel:
    """
    create a channel instance

    :param channel_type: channel type code
    :param instance_id: unique id when running several instances of the same
        channel type. Empty -> legacy single-instance behavior (the channel's
        own @singleton cache is used, exactly as before).
    :param bound_agent_id: Agent this instance routes inbound messages to.
    :param credentials: per-instance credential overrides (app_id/secret/...).
        When provided, a fresh (non-singleton) instance is built so each
        instance can carry its own credentials.
    :param members: teammate Agent ids the owner may delegate to (team bot).
    :return: channel instance
    """
    multi_instance = bool(instance_id or credentials or bound_agent_id or members)
    ch = _build_channel(channel_type)
    ch.channel_type = channel_type
    if multi_instance:
        ch.apply_instance(
            instance_id=instance_id or ch.channel_type,
            bound_agent_id=bound_agent_id,
            credentials=credentials,
            members=members,
        )
    return ch


def _build_channel(channel_type) -> Channel:
    """
    create a channel instance
    :param channel_type: channel type code
    :return: channel instance
    """
    if channel_type == "terminal":
        from channel.terminal.terminal_channel import TerminalChannel
        ch = TerminalChannel()
    elif channel_type == "web":
        from channel.web.web_channel import WebChannel
        ch = WebChannel()
    else:
        raise RuntimeError(f"unsupported channel_type: {channel_type!r}")
    ch.channel_type = channel_type
    return ch
