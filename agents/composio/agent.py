#!/usr/bin/env python3
"""Composio compatibility wrapper over unified Aider agent."""

from agents.aider.agent import AiderAgent


class ComposioBridge(AiderAgent):
    def __init__(self):
        super().__init__("composio")
