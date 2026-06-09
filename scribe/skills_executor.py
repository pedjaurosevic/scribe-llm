"""
Skills execution system for Scribe.

Loads skills from SKILL.md files and executes them based on user requests.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Skill:
    """Represents a skill with metadata and execution instructions."""

    name: str
    description: str
    path: Path
    content: str
    user_invocable: bool = False
    disable_model_invocation: bool = False

    @classmethod
    def from_path(cls, path: Path) -> Skill | None:
        """Load a skill from a directory path."""
        skill_md = path / "SKILL.md"
        if not skill_md.exists():
            return None

        content = skill_md.read_text(encoding="utf-8")

        name = path.name
        description = ""
        user_invocable = False
        disable_model_invocation = False

        frontmatter_match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        if frontmatter_match:
            frontmatter = frontmatter_match.group(1)
            for line in frontmatter.split("\n"):
                if line.startswith("name:"):
                    name = line.split(":", 1)[1].strip().strip('"').strip("'")
                elif line.startswith("description:"):
                    description = line.split(":", 1)[1].strip().strip('"').strip("'")
                elif "user-invocable" in line and "true" in line.lower():
                    user_invocable = True
                elif "disable-model-invocation" in line and "true" in line.lower():
                    disable_model_invocation = True

        return cls(
            name=name,
            description=description,
            path=path,
            content=content,
            user_invocable=user_invocable,
            disable_model_invocation=disable_model_invocation,
        )


@dataclass
class SkillResult:
    """Result of skill execution."""

    success: bool
    output: str
    skill_name: str
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class SkillsRegistry:
    """
    Registry of available skills.

    Searches standard paths for skills and provides lookup and execution.
    """

    DEFAULT_PATHS = [
        Path.home() / ".scribe" / "skills",
        Path.home() / ".config" / "scribe" / "skills",
        Path.cwd() / "skills",
        Path.cwd() / ".scribe" / "skills",
        Path(__file__).parent / "skills",  # Built-in skills in scribe/skills/
    ]

    def __init__(self, extra_paths: list[Path] | None = None):
        """Initialize skills registry."""
        self._skills: dict[str, Skill] = {}
        self._search_paths = (extra_paths or []) + self.DEFAULT_PATHS
        self._load_skills()

    def _load_skills(self) -> None:
        """Load all skills from search paths."""
        for base_path in self._search_paths:
            if not base_path.exists():
                continue

            for item in base_path.iterdir():
                if not item.is_dir():
                    continue

                skill = Skill.from_path(item)
                if skill and skill.name not in self._skills:
                    self._skills[skill.name] = skill

    def get(self, name: str) -> Skill | None:
        """Get a skill by name."""
        return self._skills.get(name)

    def list(self) -> list[Skill]:
        """List all available skills."""
        return list(self._skills.values())

    def search(self, query: str) -> list[Skill]:
        """Search skills by name or description."""
        query_lower = query.lower()
        results = []
        for skill in self._skills.values():
            if query_lower in skill.name.lower():
                results.append(skill)
            elif query_lower in skill.description.lower():
                results.append(skill)
        return results

    def find_best_skill(self, query: str) -> Skill | None:
        """
        Find the best matching skill for a query.

        Args:
            query: User's request

        Returns:
            Best matching skill or None
        """
        query_lower = query.lower()

        best_match = None
        best_score = 0

        for skill in self._skills.values():
            score = 0

            if skill.disable_model_invocation:
                continue

            if skill.name.lower() in query_lower:
                score += 10
            elif query_lower in skill.name.lower():
                score += 8

            if query_lower in skill.description.lower():
                score += 5

            words = query_lower.split()
            for word in words:
                if word in skill.description.lower():
                    score += 2
                if word in skill.name.lower():
                    score += 3

            if score > best_score:
                best_score = score
                best_match = skill

        return best_match if best_score >= 3 else None


class SkillsExecutor:
    """
    Executes skills and generates prompts for the LLM.

    Skills are markdown files that define how to perform certain tasks.
    The executor extracts the skill content and formats it for the LLM.
    """

    def __init__(self, registry: SkillsRegistry | None = None):
        """Initialize skills executor."""
        self.registry = registry or SkillsRegistry()

    def get_skill_prompt(self, skill_name: str) -> str | None:
        """
        Get the full prompt text for a skill.

        Args:
            skill_name: Name of the skill

        Returns:
            Skill content as prompt text, or None if skill not found
        """
        skill = self.registry.get(skill_name)
        if not skill:
            return None

        return self._format_skill_as_prompt(skill)

    def _format_skill_as_prompt(self, skill: Skill) -> str:
        """
        Format skill content as a prompt for the LLM.

        Strips YAML frontmatter and formats the markdown content.
        """
        content = skill.content

        frontmatter_match = re.match(r"^---\n.*?\n---\n", content, re.DOTALL)
        if frontmatter_match:
            content = content[frontmatter_match.end() :]

        content = content.strip()

        header = f"[SKILL: {skill.name}]\n"
        footer = "\n[/SKILL]"
        instruction = "\n\nFollow the instructions above to complete the task."

        return f"{header}{instruction}\n\n{content}{footer}"

    def execute_skill(
        self,
        skill_name: str,
        context: dict[str, Any],
    ) -> SkillResult:
        """
        Execute a skill with the given context.

        Args:
            skill_name: Name of skill to execute
            context: Execution context (task, user_input, etc.)

        Returns:
            SkillResult with output or error
        """
        skill = self.registry.get(skill_name)
        if not skill:
            return SkillResult(
                success=False,
                output="",
                skill_name=skill_name,
                error=f"Skill '{skill_name}' not found",
            )

        prompt = self.get_skill_prompt(skill_name)
        if not prompt:
            return SkillResult(
                success=False,
                output="",
                skill_name=skill_name,
                error="Could not format skill prompt",
            )

        return SkillResult(
            success=True,
            output=prompt,
            skill_name=skill_name,
            metadata={
                "description": skill.description,
                "user_invocable": skill.user_invocable,
            },
        )

    def should_use_skill(self, user_input: str) -> tuple[bool, str | None]:
        """
        Determine if a skill should be used for the given input.

        Args:
            user_input: User's message

        Returns:
            Tuple of (should_use, skill_name or None)
        """
        skill = self.registry.find_best_skill(user_input)
        if skill:
            return True, skill.name
        return False, None


def get_executor() -> SkillsExecutor:
    """Get a skills executor with the default registry."""
    return SkillsExecutor()


def get_registry() -> SkillsRegistry:
    """Get the global skills registry."""
    return SkillsRegistry()
