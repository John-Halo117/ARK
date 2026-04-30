#!/usr/bin/env python3
"""OpenCode compatibility wrapper over Forge-native local agent runtime."""

from agents.forge_native.agent import ForgeNativeAgent


class OpenCodeAgent(ForgeNativeAgent):
    def __init__(self):
        super().__init__("opencode")
