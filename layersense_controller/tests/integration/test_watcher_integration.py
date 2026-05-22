import pytest
from layersense_controller.watcher import start_watcher

pytestmark = [pytest.mark.integration, pytest.mark.ai]


def test_start_watcher_raises_step_7_redesign_pointer() -> None:
    """Keep the legacy watcher hard-disabled at the package boundary."""
    with pytest.raises(NotImplementedError, match="watcher disabled in Step 3"):
        start_watcher()
