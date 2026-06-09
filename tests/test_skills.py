import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scribe.skills_executor import Skill, SkillResult, SkillsExecutor, SkillsRegistry


class TestSkillsRegistry:
    def test_registry_init(self):
        registry = SkillsRegistry()
        assert registry is not None
        assert isinstance(registry._search_paths, list)

    def test_registry_loads_builtin_skills(self):
        registry = SkillsRegistry()
        skills = registry.list()
        assert len(skills) >= 3
        names = [s.name for s in skills]
        assert "deep-research" in names
        assert "writer" in names
        assert "wiki-memory" in names

    def test_registry_get_skill(self):
        registry = SkillsRegistry()
        skill = registry.get("deep-research")
        assert skill is not None
        assert isinstance(skill, Skill)
        assert skill.name == "deep-research"

    def test_registry_get_nonexistent(self):
        registry = SkillsRegistry()
        skill = registry.get("nonexistent-skill-xyz")
        assert skill is None


class TestSkillsExecutor:
    def test_executor_init(self):
        executor = SkillsExecutor()
        assert executor is not None
        assert executor.registry is not None

    def test_executor_has_skills(self):
        executor = SkillsExecutor()
        skills = executor.registry.list()
        assert len(skills) > 0


class TestSkill:
    def test_skill_from_builtin_path(self):
        skill = Skill.from_path(
            Path(__file__).parent.parent / "scribe" / "skills" / "deep-research"
        )
        assert skill is not None
        assert skill.name == "deep-research"
        assert skill.description is not None
        assert len(skill.description) > 0

    def test_skill_result(self):
        result = SkillResult(
            success=True,
            output="Test output",
            skill_name="test-skill"
        )
        assert result.success is True
        assert result.output == "Test output"
        assert result.skill_name == "test-skill"
