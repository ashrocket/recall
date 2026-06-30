"""
YAML serializers for sync artifacts.
Each artifact type has a to_yaml() and from_yaml() function.
"""

import yaml


def restart_to_yaml(restart: dict) -> str:
    return yaml.dump(restart, default_flow_style=False, sort_keys=False, allow_unicode=True)


def yaml_to_restart(text: str) -> dict:
    return yaml.safe_load(text)


def learning_to_yaml(learning: dict) -> str:
    return yaml.dump(learning, default_flow_style=False, sort_keys=False, allow_unicode=True)


def yaml_to_learning(text: str) -> dict:
    return yaml.safe_load(text)


def session_meta_to_yaml(meta: dict) -> str:
    return yaml.dump(meta, default_flow_style=False, sort_keys=False, allow_unicode=True)


def yaml_to_session_meta(text: str) -> dict:
    return yaml.safe_load(text)


def sop_to_yaml(sop: dict) -> str:
    return yaml.dump(sop, default_flow_style=False, sort_keys=False, allow_unicode=True)


def yaml_to_sop(text: str) -> dict:
    return yaml.safe_load(text)


def agent_config_to_yaml(snapshot: dict) -> str:
    return yaml.dump(snapshot, default_flow_style=False, sort_keys=False, allow_unicode=True)


def yaml_to_agent_config(text: str) -> dict:
    return yaml.safe_load(text)


def sync_filename(artifact_type: str, name: str, date: str) -> str:
    """Generate a conflict-free filename: YYYY-MM-DD_slug.yaml"""
    date_prefix = date[:10] if len(date) >= 10 else date
    slug = name.lower().replace(" ", "-").replace("/", "-")[:60]
    return f"{date_prefix}_{slug}.yaml"
