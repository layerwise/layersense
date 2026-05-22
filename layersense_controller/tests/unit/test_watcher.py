import pytest
from layersense_controller.watcher import start_watcher

pytestmark = [pytest.mark.unit, pytest.mark.ai]


def test_start_watcher_is_disabled_until_project_aware_redesign() -> None:
    """Disable the legacy watcher until Step 7 replaces it with a project-aware flow."""
    with pytest.raises(NotImplementedError, match="Step 3.*Step 7"):
        start_watcher()
