#!/usr/bin/env python3
"""Composio compatibility wrapper over Forge-native local tool runtime."""

from agents.forge_native.agent import ForgeNativeAgent


class ComposioBridge(ForgeNativeAgent):
    def __init__(self):
        super().__init__("composio")
