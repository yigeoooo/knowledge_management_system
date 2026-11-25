from test_knowledge_bases import login


def test_selected_draft_updates_in_place_and_rejects_stale_save(client):
    headers = login(client)
    url = '/api/v1/prompts/robot_persona'
    initial = client.get(url, headers=headers).json['data']['versions'][0]
    def save(base, text, note=''):
        return client.post(url + '/versions', headers=headers, json={
            'content': text, 'note': note, 'base_version_id': base['id'],
            'expected_sha256': base['sha256'], 'expected_note': base.get('note', '')})
    draft = save(initial, initial['content'] + '\n新的身份规则。').json['data']
    assert save(initial, initial['content'] + '\n另一份草稿。').status_code == 409
    updated = save(draft, draft['content'] + '\n补充规则。')
    assert updated.status_code == 200
    assert updated.json['data']['id'] == draft['id']
    assert updated.json['data']['version'] == draft['version']
    assert save(draft, draft['content'] + '\n过时编辑。').status_code == 409
    detail = client.get(url, headers=headers).json['data']
    assert len(detail['versions']) == 2
    assert detail['active_version'] == 1
    assert next(v for v in detail['versions'] if v['version'] == 1)['is_draft'] is False
