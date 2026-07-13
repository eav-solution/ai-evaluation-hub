import re
from pathlib import Path


def test_compose_runs_celery_beat_scheduler():
    compose = Path(__file__).parents[2].joinpath("docker-compose.yml").read_text()
    assert re.search(
        r"(?ms)^  beat:\n.*?^    command: celery .* beat ", compose
    )


def test_compose_disables_private_endpoints_by_default():
    compose = Path(__file__).parents[2].joinpath("docker-compose.yml").read_text()
    assert compose.count(
        "ALLOW_PRIVATE_ENDPOINTS: ${ALLOW_PRIVATE_ENDPOINTS:-false}"
    ) == 3
