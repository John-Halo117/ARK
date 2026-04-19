#!/usr/bin/env python3
"""OpenCode compatibility wrapper over unified Aider agent."""

from agents.aider.agent import AiderAgent


class OpenCodeAgent(AiderAgent):
    def __init__(self):
        super().__init__("opencode")
