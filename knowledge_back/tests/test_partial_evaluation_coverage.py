from app.application.evaluations import service
from app.core.extensions import db
from app.entities import EvaluationDataset, EvaluationExample, KnowledgeBase, PromptVersion


def test_uncovered_candidate_does_not_block_existing_questions(app, monkeypatch):
    monkeypatch.setattr(service, 'environment', lambda _: {'index': ['test-index']})
    with app.app_context():
        base = db.session.scalar(db.select(KnowledgeBase))
        dataset = EvaluationDataset(name='部分题目', knowledge_base_id=base.id)
        db.session.add(dataset); db.session.flush()
        example = EvaluationExample(dataset_id=dataset.id, name='问答题',
            inputs={'question': '介绍一下', 'robot': False}, reference={})
        candidate = PromptVersion(prompt_key='suggest_questions', version=2,
                                  content='推荐问题的新草稿', note='')
        db.session.add_all([example, candidate]); db.session.commit()
        snapshot = service.freeze(dataset, {'suggest_questions': str(candidate.id)}, False)
        assert len(snapshot['examples']) == 1
        assert 'suggest_questions' not in snapshot['covered_prompt_keys']
        assert snapshot['candidate']['suggest_questions']['id'] == str(candidate.id)
        assert snapshot['baseline']['suggest_questions']['version'] == 1
