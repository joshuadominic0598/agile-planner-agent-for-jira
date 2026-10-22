"""API compatibility for hosted and local model connections."""

import re


def legacy_chat_model(cfg):
    model = cfg.get('wire_model') or cfg.get('model', '')
    return bool(re.match(r'^(?:ft:)?gpt-(?:3\.5|35)-turbo(?:$|[-:])', model, re.I))


def api_protocol(cfg):
    if cfg['provider'] in {'compatible', 'gemini'}:
        return 'chat'
    mode = cfg.get('api_mode', 'auto')
    if mode != 'auto':
        return mode
    return 'chat' if legacy_chat_model(cfg) else 'responses'
