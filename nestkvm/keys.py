"""Serialize pynput key/button objects to plain dicts for the wire, and back.

Keys come in two shapes from pynput: KeyCode (printable chars / virtual-key
codes) and Key (named specials like shift, enter, f5). We carry char when we
have it, else the virtual-key code, else the special name.
"""

from pynput.keyboard import Key, KeyCode
from pynput.mouse import Button


def serialize_key(key):
    if isinstance(key, KeyCode):
        if key.char is not None:
            return {"k": "char", "char": key.char}
        if key.vk is not None:
            return {"k": "vk", "vk": key.vk}
        return {"k": "none"}
    # Key (special)
    return {"k": "special", "name": key.name}


def deserialize_key(d):
    if not d:
        return None
    kind = d.get("k")
    if kind == "char":
        return KeyCode.from_char(d["char"])
    if kind == "vk":
        return KeyCode.from_vk(d["vk"])
    if kind == "special":
        return getattr(Key, d["name"], None)
    return None


def serialize_button(button) -> str:
    return button.name


def deserialize_button(name):
    return getattr(Button, name, Button.left)
