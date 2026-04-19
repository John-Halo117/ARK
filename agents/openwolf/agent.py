#!/usr/bin/env python3
"""OpenWolf compatibility wrapper over unified Aider agent."""

from agents.aider.agent import AiderAgent


class OpenWolfAgent(AiderAgent):
    def __init__(self):
        super().__init__("openwolf")
