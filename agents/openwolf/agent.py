#!/usr/bin/env python3
"""OpenWolf compatibility wrapper over Forge-native local agent runtime."""

from agents.forge_native.agent import ForgeNativeAgent


class OpenWolfAgent(ForgeNativeAgent):
    def __init__(self):
        super().__init__("openwolf")
