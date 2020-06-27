from dataclasses import dataclass
from pprint import pformat
from unittest.mock import patch

from pymw import API, LoginError, APIError
from pytest import fixture


api = API('https://www.mediawiki.org/w/api.php')


@fixture
def cleared_api():
    api.clear_cache()
    return api


def fake_sleep(_):
    return


@dataclass
class FakeResp:
    headers: dict
    _json: dict

    def json(self):
        return self._json


def patch_post(obj, attr, return_values):
    def fake_post(return_value):
        def fake_post_closure():
            return return_value
        return fake_post_closure()
    return patch.object(
        obj, attr, side_effect=[fake_post(rv) for rv in return_values])


def api_post_patch(*return_values: dict):
    return patch_post(API, 'post', return_values)


def session_post_patch(*return_values: dict):
    iterator = iter(return_values)
    return patch_post(api.session, 'post', (
        FakeResp(headers, json) for headers, json in zip(iterator, iterator)))


@api_post_patch(
    {'batchcomplete': True, 'query': {'tokens': {'logintoken': 'T'}}},
    {'login': {'result': 'Success', 'lguserid': 1, 'lgusername': 'U'}})
def test_login(post_mock):
    api.login(lgname='U', lgpassword='P')
    for call, expected_kwargs in zip(post_mock.mock_calls, (
        {'action': 'query', 'meta': 'tokens', 'type': 'login'},
        {'action': 'login', 'lgname': 'U', 'lgpassword': 'P', 'lgtoken': 'T'})
    ):
        assert call.kwargs == expected_kwargs


@api_post_patch(
    {'batchcomplete': True, 'query': {'tokens': {'logintoken': 'T1'}}},
    {'login': {'result': 'WrongToken'}},
    {'batchcomplete': True, 'query': {'tokens': {'logintoken': 'T2'}}},
    {'login': {'result': 'Success', 'lguserid': 1, 'lgusername': 'U'}})
def test_bad_login_token(post_mock):
    api.login(lgname='U', lgpassword='P')
    for call, expected_kwargs in zip(post_mock.mock_calls, (
        {'action': 'query', 'meta': 'tokens', 'type': 'login'},
        {'action': 'login', 'lgtoken': 'T1', 'lgname': 'U', 'lgpassword': 'P'},
        {'action': 'query', 'meta': 'tokens', 'type': 'login'},
        {'action': 'login', 'lgtoken': 'T2', 'lgname': 'U', 'lgpassword': 'P'},)
    ):
        assert call.kwargs == expected_kwargs


@api_post_patch({'login': {'result': 'U', 'lguserid': 1, 'lgusername': 'U'}})
def test_unknown_login_result(post_mock):
    api.login_token = 'T'
    try:
        api.login(lgname='U', lgpassword='P')
    except LoginError:
        pass
    else:  # pragma: nocover
        raise AssertionError('LoginError was not raised')
    assert len(post_mock.mock_calls) == 1


@api_post_patch(
    {'batchcomplete': True, 'continue': {'rccontinue': '20190908072938|4484663', 'continue': '-||'}, 'query': {'recentchanges': [{'type': 'log', 'timestamp': '2019-09-08T07:30:00Z'}]}},
    {'batchcomplete': True, 'query': {'recentchanges': [{'type': 'categorize', 'timestamp': '2019-09-08T07:29:38Z'}]}})
def test_recentchanges(post_mock):
    assert [rc for rc in api.recentchanges(rclimit=1, rcprop='timestamp')] == [
            {'type': 'log', 'timestamp': '2019-09-08T07:30:00Z'},
            {'type': 'categorize', 'timestamp': '2019-09-08T07:29:38Z'}]
    post1_call_data = {'list': 'recentchanges', 'rcprop': 'timestamp', 'rclimit': 1, 'action': 'query'}
    post2_call_data = {**post1_call_data, 'rccontinue': '20190908072938|4484663', 'continue': '-||'}
    for call, kwargs in zip(post_mock.mock_calls, (post1_call_data, post2_call_data)):
        assert call.kwargs == kwargs


@patch('pymw._api.sleep', fake_sleep)
@patch('pymw._api.warning')
@session_post_patch(
    {'retry-after': '5'},
    {'errors': [{'code': 'maxlag', 'text': 'Waiting for 10.64.16.7: 0.80593395233154 seconds lagged.', 'data': {'host': '10.64.16.7', 'lag': 0.805933952331543, 'type': 'db'}, 'module': 'main'}], 'docref': 'See https://www.mediawiki.org/w/api.php for API usage. Subscribe to the mediawiki-api-announce mailing list at &lt;https://lists.wikimedia.org/mailman/listinfo/mediawiki-api-announce&gt; for notice of API deprecations and breaking changes.', 'servedby': 'mw1225'},
    {}, {'batchcomplete': True, 'query': {'tokens': {'watchtoken': '+\\'}}})
def test_maxlag(post_mock, warning_mock, cleared_api):
    tokens = cleared_api.tokens('watch')
    assert tokens == {'watchtoken': '+\\'}
    post_data = {'meta': 'tokens', 'type': 'watch', 'action': 'query', 'format': 'json', 'formatversion': '2', 'errorformat': 'plaintext', 'maxlag': 5}
    assert [c.kwargs['data'] for c in post_mock.mock_calls] == \
        [post_data, post_data]
    warning_mock.assert_called_with('maxlag error (retrying after 5 seconds)')


@api_post_patch({'batchcomplete': True, 'query': {'protocols': ['http://', 'https://']}})
def test_siteinfo(post_mock):
    si = api.siteinfo(siprop='protocols')
    assert si == {'protocols': ['http://', 'https://']}
    calls = post_mock.mock_calls
    assert len(calls) == 1
    assert calls[0].kwargs == {'action': 'query', 'meta': 'siteinfo', 'siprop': 'protocols'}


@api_post_patch(
    {'continue': {'llcontinue': '15580374|bg', 'continue': '||'}, 'query': {'pages': [{'pageid': 15580374, 'ns': 0, 'title': 'Main Page', 'langlinks': [{'lang': 'ar', 'title': ''}]}]}},
    {'batchcomplete': True, 'query': {'pages': [{'pageid': 15580374, 'ns': 0, 'title': 'Main Page', 'langlinks': [{'lang': 'zh', 'title': ''}]}]}})
def test_langlinks(post_mock):
    titles_langlinks = [page_ll for page_ll in api.langlinks(
        titles='Main Page', lllimit=1)]
    assert len(titles_langlinks) == 1
    for call, kwargs in zip(post_mock.mock_calls, (
        {'action': 'query', 'prop': 'langlinks', 'lllimit': 1, 'titles': 'Main Page'},
        {'action': 'query', 'prop': 'langlinks', 'lllimit': 1, 'titles': 'Main Page', 'llcontinue': '15580374|bg', 'continue': '||'}
    )):
        assert call.kwargs == kwargs
    assert titles_langlinks[0] == {'pageid': 15580374, 'ns': 0, 'title': 'Main Page', 'langlinks': [{'lang': 'ar', 'title': ''}, {'lang': 'zh', 'title': ''}]}


@api_post_patch({'batchcomplete': True, 'query': {'pages': [{'pageid': 1182793, 'ns': 0, 'title': 'Main Page'}]}, 'limits': {'langlinks': 500}})
def test_lang_links_title_not_exists(post_mock):
    titles_langlinks = [page_ll for page_ll in api.langlinks(
        titles='Main Page')]
    assert len(titles_langlinks) == 1
    assert post_mock.mock_calls[0].kwargs == {'action': 'query', 'prop': 'langlinks', 'lllimit': 'max', 'titles': 'Main Page'}
    assert titles_langlinks[0] == {'pageid': 1182793, 'ns': 0, 'title': 'Main Page'}


@api_post_patch({'batchcomplete': True, 'query': {'userinfo': {'id': 0, 'name': '1.1.1.1', 'anon': True}}})
def test_userinfo(post_mock):
    assert api.userinfo() == {'id': 0, 'name': '1.1.1.1', 'anon': True}
    assert post_mock.mock_calls[0].kwargs == {'action': 'query', 'meta': 'userinfo'}


@api_post_patch({'batchcomplete': True, 'query': {'repos': [{'displayname': 'Commons'}, {'displayname': 'Wikipedia'}]}})
def test_filerepoinfo(post_mock):
    assert api.filerepoinfo(friprop='displayname') == [{'displayname': 'Commons'}, {'displayname': 'Wikipedia'}]
    assert post_mock.mock_calls[0].kwargs == {'action': 'query', 'meta': 'filerepoinfo', 'friprop': 'displayname'}


def test_context_manager():
    a = API('')
    with patch.object(a.session, 'close') as close_mock:
        with a:
            pass
    close_mock.assert_called_once_with()


@session_post_patch(
    {}, {'batchcomplete': True, 'query': {'tokens': {'patroltoken': '+\\'}}},
    {}, {'errors': [{'code': 'permissiondenied', 'text': 'T', 'module': 'patrol'}], 'docref': 'D', 'servedby': 'mw1233'})
def test_patrol_not_logged_in(post_mock, cleared_api):
    try:
        cleared_api.patrol(revid=27040231)
    except APIError:
        pass
    else:  # pragma: nocover
        raise AssertionError('APIError was not raised')
    post_mock.assert_called_with(
        'https://www.mediawiki.org/w/api.php',
        data={'revid': 27040231, 'action': 'patrol', 'token': '+\\', 'format': 'json', 'formatversion': '2', 'errorformat': 'plaintext', 'maxlag': 5})


@api_post_patch({'patrol': {'rcid': 1, 'ns': 4, 'title': 'T'}})
def test_patrol(post_mock):
    api.patrol_token = '+'
    api.patrol(revid=1)
    post_mock.assert_called_with(action='patrol', token='+', revid=1)


@session_post_patch({}, {'errors': [{'code': 'badtoken', 'text': 'Invalid CSRF token.', 'module': 'patrol'}], 'docref': 'D', 'servedby': 'mw1279'})
def test_bad_patrol_token(_):
    api.patrol_token = '+'
    try:
        api.patrol(revid=1)
    except APIError:
        pass
    else:  # pragma: nocover
        raise AssertionError('APIError was not raised')
    with patch.object(API, 'tokens', return_value={'patroltoken': 'N'}) as tokens_mock:
        assert api.patrol_token == 'N'
    tokens_mock.assert_called_once_with('patrol')


def test_rawcontinue():
    try:
        for _ in api.query(rawcontinue=''):
            pass
    except NotImplementedError:
        pass
    else:  # pragma: nocover
        raise AssertionError('rawcontinue did not raise in query')


@patch('pymw._api.warning')
def test_warnings(warning_mock):
    warnings = [{'code': 'unrecognizedparams', 'text': 'Unrecognized parameter: unknown_param.', 'module': 'main'}]
    with session_post_patch(
        {}, {'warnings': warnings, 'batchcomplete': True}
    ):
        api.post()
    warning_mock.assert_called_once_with(pformat(warnings))


@api_post_patch({})
def test_logout(post_mock):
    api.csrf_token = 'T'
    api.logout()
    post_mock.assert_called_once()
    assert api._csrf_token is None


@api_post_patch({'batchcomplete': True, 'query': {'tokens': {'csrftoken': '+\\'}}})
def test_csrf_token(post_mock):
    assert api.csrf_token == '+\\'
    post_mock.assert_called_once()


@api_post_patch({'batchcomplete': True, 'query': {'logevents': [{'timestamp': '2004-12-23T18:41:10Z'}]}})
def test_logevents(post_mock):
    events = [e for e in api.logevents(1, leprop='timestamp', ledir='newer', leend='2004-12-23T18:41:10Z')]
    assert len(events) == 1
    assert events[0] == {'timestamp': '2004-12-23T18:41:10Z'}
    assert post_mock.mock_calls[0].kwargs == {'action': 'query', 'list': 'logevents', 'lelimit': 1, 'leprop': 'timestamp', 'ledir': 'newer', 'leend': '2004-12-23T18:41:10Z'}


@api_post_patch({'batchcomplete': True, 'query': {'normalized': [{'fromencoded': False, 'from': 'a', 'to': 'A'}, {'fromencoded': False, 'from': 'b', 'to': 'B'}], 'pages': [{'pageid': 91945, 'ns': 0, 'title': 'A', 'revisions': [{'revid': 28594859, 'parentid': 28594843, 'minor': False, 'user': '5.119.128.223', 'anon': True, 'timestamp': '2020-03-31T11:38:15Z', 'comment': 'c1'}]}, {'pageid': 91946, 'ns': 0, 'title': 'B', 'revisions': [{'revid': 28199506, 'parentid': 25110220, 'minor': False, 'user': '2.147.31.47', 'anon': True, 'timestamp': '2020-02-08T14:53:12Z', 'comment': 'c2'}]}]}})
def test_revisions_mode13(_):
    assert [
        {'pageid': 91945, 'ns': 0, 'title': 'A', 'revisions': [{'revid': 28594859, 'parentid': 28594843, 'minor': False, 'user': '5.119.128.223', 'anon': True, 'timestamp': '2020-03-31T11:38:15Z', 'comment': 'c1'}]},
        {'pageid': 91946, 'ns': 0, 'title': 'B', 'revisions': [{'revid': 28199506, 'parentid': 25110220, 'minor': False, 'user': '2.147.31.47', 'anon': True, 'timestamp': '2020-02-08T14:53:12Z', 'comment': 'c2'}]}
    ] == [r for r in api.revisions(titles='a|b')]


@api_post_patch({'batchcomplete': True, 'query': {'pages': [{'pageid': 112963, 'ns': 0, 'title': 'DmazaTest', 'revisions': [{'revid': 438026, 'parentid': 438023, 'minor': False, 'user': 'DMaza (WMF)', 'timestamp': '2020-06-25T21:09:52Z', 'comment': ''}, {'revid': 438023, 'parentid': 438022, 'minor': False, 'user': 'DMaza (WMF)', 'timestamp': '2020-06-25T21:08:12Z', 'comment': ''}, {'revid': 438022, 'parentid': 0, 'minor': False, 'user': 'DMaza (WMF)', 'timestamp': '2020-06-25T21:08:02Z', 'comment': '1'}]}]}, 'limits': {'revisions': 500}})
def test_revisions_mode2_no_rvlimit(post_mock):  # auto set rvlimit
    assert [
        {'ns': 0, 'pageid': 112963, 'revisions': [{'comment': '', 'minor': False, 'parentid': 438023, 'revid': 438026, 'timestamp': '2020-06-25T21:09:52Z', 'user': 'DMaza (WMF)'}, {'comment': '', 'minor': False, 'parentid': 438022, 'revid': 438023, 'timestamp': '2020-06-25T21:08:12Z', 'user': 'DMaza (WMF)'}, {'comment': '1', 'minor': False, 'parentid': 0, 'revid': 438022, 'timestamp': '2020-06-25T21:08:02Z', 'user': 'DMaza (WMF)'}], 'title': 'DmazaTest'}
    ] == [r for r in api.revisions(titles='DmazaTest', rvstart='now')]
    assert post_mock.mock_calls[0].kwargs == {'action': 'query', 'prop': 'revisions', 'titles': 'DmazaTest', 'rvstart': 'now', 'rvlimit': 'max'}
