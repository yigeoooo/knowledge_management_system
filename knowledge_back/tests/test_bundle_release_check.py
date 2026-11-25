from types import SimpleNamespace
from copy import deepcopy
import pytest
from app.api.prompts.controller import bundle_versions
from app.application.prompts.registry import published_snapshot, version_data
from app.core.extensions import db
from app.core.http import ApiError
from app.entities import PromptVersion


def test_bundle_check_uses_live_versions_and_rejects_already_published(app, monkeypatch):
    from app.api.prompts import controller
    with app.app_context():
        current = published_snapshot()
        run = SimpleNamespace(snapshot={'candidate': deepcopy(current)}, dataset_id=None)
        with pytest.raises(ApiError, match='没有需要发布'):
            bundle_versions(run)
        draft = PromptVersion(prompt_key='robot_persona', version=2, content='测试草稿内容', note='')
        db.session.add(draft); db.session.flush()
        run.snapshot['candidate']['robot_persona'] = version_data(draft)
        def check(version, experiment, baseline, **kwargs):
            assert kwargs['bundle'] is True
            return [] if version_data(version) == experiment.snapshot['candidate'][version.prompt_key] else ['草稿已修改']
        monkeypatch.setattr(controller, 'release_reasons', check)
        assert bundle_versions(run) == [draft]
        draft.content = '测试后修改的草稿内容'
        with pytest.raises(ApiError, match='草稿已修改'):
            bundle_versions(run)
