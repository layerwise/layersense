import pytest
from layersense_persistence.repositories.projects import ProjectsRepository

pytestmark = [pytest.mark.unit, pytest.mark.ai]


def test_create_project_derives_stable_unique_slugs(session) -> None:
    """Derive URL-safe project slugs and resolve collisions."""
    projects = ProjectsRepository(session)

    first = projects.create(name="Über Cool Project!!!")
    second = projects.create(name="Uber Cool Project")

    assert first.slug == "uber-cool-project"
    assert second.slug == "uber-cool-project-2"


def test_update_project_changes_mutable_fields(session) -> None:
    """Update project name and default render config."""
    projects = ProjectsRepository(session)
    project = projects.create(name="Demo")

    updated = projects.update(
        project.id, name="Renamed", default_render_config_json='{"quality":"l"}'
    )

    assert updated.name == "Renamed"
    assert updated.default_render_config_json == '{"quality":"l"}'


def test_delete_missing_project_raises_key_error(session) -> None:
    """Raise KeyError when deleting a missing project."""
    with pytest.raises(KeyError):
        ProjectsRepository(session).delete("missing")
