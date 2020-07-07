from io import BytesIO
from itertools import groupby, takewhile
from pprint import pformat
from unittest.mock import call, patch, mock_open

from pytest import fixture, raises

from pymw import API, LoginError, APIError


url = 'https://www.mediawiki.org/w/api.php'
api = API(url)


@fixture
def cleared_api():
    api.clear_cache()
    return api


def fake_sleep(_):
    return


class FakeResp:
    __slots__ = ('_json', 'headers')

    def __init__(self, json, headers={}):
        self._json = json
        self.headers = headers

    def json(self):
        return self._json


def patch_post(obj, attr, call_returns, ):
    i = -2

    def side_effect(*args, **kwargs):
        nonlocal i
        i += 2
        if (call := call_returns[i]) is not any:
            assert args == call.args
            assert kwargs == call.kwargs
        return call_returns[i + 1]

    return patch.object(obj, attr, side_effect=side_effect)


def api_post_patch(*call_returns):
    return patch_post(API, 'post', call_returns)


def session_post_patch(*call_header_returns):
    call_responses = []
    iterator = iter(call_header_returns)
    call = next(iterator)
    while call is not None:
        headers_or_json = next(iterator)
        json_or_call = next(iterator, None)
        if type(json_or_call) is dict:
            response = FakeResp(json=json_or_call, headers=headers_or_json)
            call_responses += (call, response)
            call = next(iterator, None)
        else:
            response = FakeResp(json=headers_or_json)
            call_responses += (call, response)
            call = json_or_call
    return patch_post(api.session, 'post', call_responses)


@api_post_patch(
    call({'action': 'query', 'meta': 'tokens', 'type': 'login'}),
    {'batchcomplete': True, 'query': {'tokens': {'logintoken': 'T'}}},
    call({'action': 'login', 'lgname': 'U', 'lgpassword': 'P', 'lgtoken': 'T'}),
    {'login': {'result': 'Success', 'lguserid': 1, 'lgusername': 'U'}})
def test_login(_):
    api.login(lgname='U', lgpassword='P')


@api_post_patch(
    call({'action': 'query', 'meta': 'tokens', 'type': 'login'}),
    {'batchcomplete': True, 'query': {'tokens': {'logintoken': 'T1'}}},
    call({'action': 'login', 'lgtoken': 'T1', 'lgname': 'U', 'lgpassword': 'P'}),
    {'login': {'result': 'WrongToken'}},
    call({'action': 'query', 'meta': 'tokens', 'type': 'login'}),
    {'batchcomplete': True, 'query': {'tokens': {'logintoken': 'T2'}}},
    call({'action': 'login', 'lgtoken': 'T2', 'lgname': 'U', 'lgpassword': 'P'}),
    {'login': {'result': 'Success', 'lguserid': 1, 'lgusername': 'U'}})
def test_bad_login_token(_):
    api.login(lgname='U', lgpassword='P')


@api_post_patch(
    any, {'login': {'result': 'U', 'lguserid': 1, 'lgusername': 'U'}})
def test_unknown_login_result(post_mock):
    api.tokens['login'] = 'T'
    try:
        api.login(lgname='U', lgpassword='P')
    except LoginError:
        pass
    else:  # pragma: nocover
        raise AssertionError('LoginError was not raised')
    assert len(post_mock.mock_calls) == 1


@api_post_patch(
    call({'list': 'recentchanges', 'rcprop': 'timestamp', 'rclimit': 1, 'action': 'query'}),
    {'batchcomplete': True, 'continue': {'rccontinue': '20190908072938|4484663', 'continue': '-||'}, 'query': {'recentchanges': [{'type': 'log', 'timestamp': '2019-09-08T07:30:00Z'}]}},
    call({'list': 'recentchanges', 'rcprop': 'timestamp', 'rclimit': 1, 'action': 'query', 'rccontinue': '20190908072938|4484663', 'continue': '-||'}),
    {'batchcomplete': True, 'query': {'recentchanges': [{'type': 'categorize', 'timestamp': '2019-09-08T07:29:38Z'}]}})
def test_recentchanges(_):
    assert [rc for rc in api.query_list('recentchanges', rclimit=1, rcprop='timestamp')] == [
            {'type': 'log', 'timestamp': '2019-09-08T07:30:00Z'},
            {'type': 'categorize', 'timestamp': '2019-09-08T07:29:38Z'}]


@patch('pymw._api.sleep', fake_sleep)
@patch('pymw._api.warning')
@session_post_patch(
    call(url, data={
        'action': 'query', 'errorformat': 'plaintext', 'format': 'json',
        'formatversion': '2', 'maxlag': 5, 'meta': 'tokens', 'type': 'watch'
    }, files=None),
    {'retry-after': '5'}, {'errors': [{'code': 'maxlag', 'text': 'Waiting for 10.64.16.7: 0.80593395233154 seconds lagged.', 'data': {'host': '10.64.16.7', 'lag': 0.805933952331543, 'type': 'db'}, 'module': 'main'}], 'docref': 'See https://www.mediawiki.org/w/api.php for API usage. Subscribe to the mediawiki-api-announce mailing list at &lt;https://lists.wikimedia.org/mailman/listinfo/mediawiki-api-announce&gt; for notice of API deprecations and breaking changes.', 'servedby': 'mw1225'},
    call(url, data={
        'meta': 'tokens', 'type': 'watch', 'action': 'query', 'format': 'json',
        'formatversion': '2', 'errorformat': 'plaintext', 'maxlag': 5
    }, files=None),
    {}, {'batchcomplete': True, 'query': {'tokens': {'watchtoken': '+\\'}}})
def test_maxlag(_, warning_mock, cleared_api):
    tokens = cleared_api.query_meta('tokens', type='watch')
    assert tokens == {'watchtoken': '+\\'}
    warning_mock.assert_called_with('maxlag error (retrying after 5 seconds)')


@api_post_patch(
    call({'action': 'query', 'meta': 'siteinfo', 'siprop': 'protocols'}),
    {'batchcomplete': True, 'query': {'protocols': ['http://', 'https://']}})
def test_siteinfo(post_mock):
    si = api.query_meta('siteinfo', siprop='protocols')
    assert si == {'protocols': ['http://', 'https://']}
    post_mock.assert_called_once()


@api_post_patch(
    call({'action': 'query', 'prop': 'langlinks', 'lllimit': 1, 'titles': 'Main Page'}),
    {'continue': {'llcontinue': '15580374|bg', 'continue': '||'}, 'query': {'pages': [{'pageid': 15580374, 'ns': 0, 'title': 'Main Page', 'langlinks': [{'lang': 'ar', 'title': ''}]}]}},
    call({'action': 'query', 'prop': 'langlinks', 'lllimit': 1, 'titles': 'Main Page', 'llcontinue': '15580374|bg', 'continue': '||'}),
    {'batchcomplete': True, 'query': {'pages': [{'pageid': 15580374, 'ns': 0, 'title': 'Main Page', 'langlinks': [{'lang': 'zh', 'title': ''}]}]}})
def test_langlinks(_):
    titles_langlinks = [page_ll for page_ll in api.query_prop(
        'langlinks', titles='Main Page', lllimit=1)]
    assert len(titles_langlinks) == 1
    assert titles_langlinks[0] == {'pageid': 15580374, 'ns': 0, 'title': 'Main Page', 'langlinks': [{'lang': 'ar', 'title': ''}, {'lang': 'zh', 'title': ''}]}


@api_post_patch(
    call({'action': 'query', 'prop': 'langlinks', 'titles': 'Main Page'}),
    {'batchcomplete': True, 'query': {'pages': [{'pageid': 1182793, 'ns': 0, 'title': 'Main Page'}]}, 'limits': {'langlinks': 500}})
def test_lang_links_title_not_exists(post_mock):
    titles_langlinks = [page_ll for page_ll in api.query_prop(
        'langlinks', titles='Main Page')]
    assert len(titles_langlinks) == 1
    post_mock.assert_called_once()
    assert titles_langlinks[0] == {'pageid': 1182793, 'ns': 0, 'title': 'Main Page'}


@api_post_patch(
    call({'action': 'query', 'meta': 'userinfo'}),
    {'batchcomplete': True, 'query': {'userinfo': {'id': 0, 'name': '1.1.1.1', 'anon': True}}})
def test_userinfo(post_mock):
    assert api.query_meta('userinfo') == {'id': 0, 'name': '1.1.1.1', 'anon': True}
    post_mock.assert_called_once()


@api_post_patch(
    call({'action': 'query', 'meta': 'filerepoinfo', 'friprop': 'displayname'}),
    {'batchcomplete': True, 'query': {'repos': [{'displayname': 'Commons'}, {'displayname': 'Wikipedia'}]}})
def test_filerepoinfo(post_mock):
    assert api.query_meta('filerepoinfo', friprop='displayname') ==\
           [{'displayname': 'Commons'}, {'displayname': 'Wikipedia'}]
    post_mock.assert_called_once()


def test_context_manager():
    a = API('')
    with patch.object(a.session, 'close') as close_mock:
        with a:
            pass
    close_mock.assert_called_once_with()


@session_post_patch(
    any, {}, {'batchcomplete': True, 'query': {'tokens': {'patroltoken': '+\\'}}},
    call(url, data={
        'revid': 27040231, 'action': 'patrol', 'token': '+\\', 'format':
            'json', 'formatversion': '2', 'errorformat': 'plaintext', 'maxlag': 5
    }, files=None), {}, {'errors': [{'code': 'permissiondenied', 'text': 'T', 'module': 'patrol'}], 'docref': 'D', 'servedby': 'mw1233'})
def test_patrol_not_logged_in(_, cleared_api):
    try:
        cleared_api.patrol(revid=27040231)
    except APIError:
        pass
    else:  # pragma: nocover
        raise AssertionError('APIError was not raised')


@api_post_patch(
    call({'action': 'patrol', 'token': 'T', 'revid': 1}),
    {'patrol': {'rcid': 1, 'ns': 4, 'title': 'T'}})
def test_patrol(post_mock):
    api.tokens['patrol'] = 'T'
    api.patrol(revid=1)
    post_mock.assert_called_once()


@session_post_patch(any, {}, {'errors': [{'code': 'badtoken', 'text': 'Invalid CSRF token.', 'module': 'patrol'}], 'docref': 'D', 'servedby': 'mw1279'})
def test_bad_patrol_token(_):
    api.tokens['patrol'] = 'T'
    try:
        api.patrol(revid=1)
    except APIError:
        pass
    else:  # pragma: nocover
        raise AssertionError('APIError was not raised')
    with patch.object(
            API, 'query_meta', return_value={'patroltoken': 'N'}) as m:
        assert api.tokens['patrol'] == 'N'
    m.assert_called_once_with('tokens', type='patrol')


def test_rawcontinue():
    try:
        for _ in api.query({'rawcontinue': ''}):
            pass  # pragma: nocover
    except NotImplementedError:
        pass
    else:  # pragma: nocover
        raise AssertionError('rawcontinue did not raise in query')


@patch('pymw._api.warning')
def test_warnings(warning_mock):
    warnings = [{'code': 'unrecognizedparams', 'text': 'Unrecognized parameter: unknown_param.', 'module': 'main'}]
    with session_post_patch(any, {}, {'warnings': warnings, 'batchcomplete': True}):
        api.post({})
    warning_mock.assert_called_once_with(pformat(warnings))


@api_post_patch(any, {})
def test_logout(post_mock):
    api.tokens['csrf'] = 'T'
    api.logout()
    post_mock.assert_called_once()
    assert 'csrf' not in api.tokens


@api_post_patch(
    any, {'batchcomplete': True, 'query': {'tokens': {'csrftoken': '+\\'}}})
def test_csrf_token(post_mock):
    assert api.tokens['csrf'] == '+\\'
    post_mock.assert_called_once()


@api_post_patch(
    call({'action': 'query', 'list': 'logevents', 'lelimit': 1, 'leprop': 'timestamp', 'ledir': 'newer', 'leend': '2004-12-23T18:41:10Z'}),
    {'batchcomplete': True, 'query': {'logevents': [{'timestamp': '2004-12-23T18:41:10Z'}]}})
def test_logevents(post_mock):
    events = [e for e in api.query_list('logevents', lelimit=1, leprop='timestamp', ledir='newer', leend='2004-12-23T18:41:10Z')]
    assert len(events) == 1
    assert events[0] == {'timestamp': '2004-12-23T18:41:10Z'}
    post_mock.assert_called_once()


@api_post_patch(any, {'batchcomplete': True, 'query': {'normalized': [{'fromencoded': False, 'from': 'a', 'to': 'A'}, {'fromencoded': False, 'from': 'b', 'to': 'B'}], 'pages': [{'pageid': 91945, 'ns': 0, 'title': 'A', 'revisions': [{'revid': 28594859, 'parentid': 28594843, 'minor': False, 'user': '5.119.128.223', 'anon': True, 'timestamp': '2020-03-31T11:38:15Z', 'comment': 'c1'}]}, {'pageid': 91946, 'ns': 0, 'title': 'B', 'revisions': [{'revid': 28199506, 'parentid': 25110220, 'minor': False, 'user': '2.147.31.47', 'anon': True, 'timestamp': '2020-02-08T14:53:12Z', 'comment': 'c2'}]}]}})
def test_revisions_mode13(_):
    assert [
        {'pageid': 91945, 'ns': 0, 'title': 'A', 'revisions': [{'revid': 28594859, 'parentid': 28594843, 'minor': False, 'user': '5.119.128.223', 'anon': True, 'timestamp': '2020-03-31T11:38:15Z', 'comment': 'c1'}]},
        {'pageid': 91946, 'ns': 0, 'title': 'B', 'revisions': [{'revid': 28199506, 'parentid': 25110220, 'minor': False, 'user': '2.147.31.47', 'anon': True, 'timestamp': '2020-02-08T14:53:12Z', 'comment': 'c2'}]}
    ] == [r for r in api.query_prop('revisions', titles='a|b')]


@api_post_patch(
    call({'action': 'query', 'prop': 'revisions', 'titles': 'DmazaTest', 'rvstart': 'now'}),
    {'batchcomplete': True, 'query': {'pages': [{'pageid': 112963, 'ns': 0, 'title': 'DmazaTest', 'revisions': [{'revid': 438026, 'parentid': 438023, 'minor': False, 'user': 'DMaza (WMF)', 'timestamp': '2020-06-25T21:09:52Z', 'comment': ''}, {'revid': 438023, 'parentid': 438022, 'minor': False, 'user': 'DMaza (WMF)', 'timestamp': '2020-06-25T21:08:12Z', 'comment': ''}, {'revid': 438022, 'parentid': 0, 'minor': False, 'user': 'DMaza (WMF)', 'timestamp': '2020-06-25T21:08:02Z', 'comment': '1'}]}]}, 'limits': {'revisions': 500}})
def test_revisions_mode2_no_rvlimit(post_mock):  # auto set rvlimit
    assert [
        {'ns': 0, 'pageid': 112963, 'revisions': [{'comment': '', 'minor': False, 'parentid': 438023, 'revid': 438026, 'timestamp': '2020-06-25T21:09:52Z', 'user': 'DMaza (WMF)'}, {'comment': '', 'minor': False, 'parentid': 438022, 'revid': 438023, 'timestamp': '2020-06-25T21:08:12Z', 'user': 'DMaza (WMF)'}, {'comment': '1', 'minor': False, 'parentid': 0, 'revid': 438022, 'timestamp': '2020-06-25T21:08:02Z', 'user': 'DMaza (WMF)'}], 'title': 'DmazaTest'}
    ] == [r for r in api.query_prop('revisions', titles='DmazaTest', rvstart='now')]
    post_mock.assert_called_once()


@api_post_patch(
    call({'action': 'upload', 'token': 'T', 'filename': 'FN.jpg'}, files={'file': ('FN.jpg', NotImplemented)}),
    {'upload': {'result': 'Warning', 'warnings': {'exists': 'Test.jpg', 'nochange': {'timestamp': '2020-07-04T07:29:07Z'}}, 'filekey': 'tampered.y27er1.18.jpg', 'sessionkey': 'tampered.y27er1.18.jpg'}})
def test_upload_file(post_mock):
    api._assert_user = 'James Bond'
    api.tokens['csrf'] = 'T'
    api.upload_file(file=NotImplemented, filename='FN.jpg')
    post_mock.assert_called_once()


@patch.object(API, 'login')
def test_upload_file_auto_login(login_mock):
    login_mock.side_effect = NotImplementedError
    api._assert_user = None
    with raises(NotImplementedError):
        api.upload_file(file=NotImplemented, filename='FN.jpg')
    login_mock.assert_called_once_with()


bio0 = BytesIO(b'0')
bio1 = BytesIO(b'1')


@api_post_patch(
    call(
        {'action': 'upload', 'token': 'T', 'stash': 1, 'offset': 0, 'filename': 'F.jpg', 'filesize': 5039, 'ignorewarnings': True},
        files={'chunk': ('F.jpg', bio0)}),
    {'upload': {'warnings': {'duplicate-archive': 'F.jpg'}, 'result': 'Continue', 'offset': 3000, 'filekey': 'K'}},
    call(
        {'action': 'upload', 'token': 'T', 'stash': 1, 'offset': 3000, 'filename': 'F.jpg', 'filesize': 5039, 'ignorewarnings': True, 'filekey': 'K'},
        files={'chunk': ('F.jpg', bio1)}),
    {'upload': {'filekey': 'K.jpg', 'imageinfo': {'CENSORED': ...}, 'result': 'Success', 'warnings': {'duplicate-archive': 'T.jpg'}}},
    call(
        {'action': 'upload', 'token': 'T', 'filename': 'F.jpg', 'ignorewarnings': True, 'filekey': 'K.jpg'},
        files=None),
    {'upload': {'filename': 'F.jpg', 'imageinfo': {'CENSORED': ...}, 'result': 'Success'}})
def test_upload_chunks(_):
    api._assert_user = 'U'
    api.tokens['csrf'] = 'T'

    result = api.upload_chunks(
        chunks=(b for b in (bio0, bio1)),
        filename='F.jpg',
        filesize=5039,
        ignorewarnings=True)
    assert result == {'filename': 'F.jpg', 'imageinfo': {'CENSORED': ...}, 'result': 'Success'}


pymw_toml = '''
version = 1

['https://www.mediawiki.org/w/api.php'.login]
'username@toolname' = 'bot_password'
'''
pymw_toml_mock = mock_open(read_data=pymw_toml)


@patch('pymw._api.Path.open', pymw_toml_mock)
@api_post_patch(any, {}, any, {})
def test_login_config(post_mock):
    post_call_data = {
        'action': 'login', 'lgname': 'username@toolname',
        'lgpassword': 'bot_password', 'lgtoken': 'LOGIN_TOKEN'}
    api.tokens['login'] = 'LOGIN_TOKEN'
    with raises(KeyError):  # because of invalid api_post_patch response
        api.login()  # without username
    post_mock.assert_called_once_with(post_call_data)
    with raises(KeyError):  # again, because of invalid api_post_patch response
        api.login('username@toolname')  # without username
    # note that assert_called_with only checks the last call
    post_mock.assert_called_with(post_call_data)
    pymw_toml_mock.assert_called_once()


@session_post_patch(any, {}, {})
def test_assert_login(post_mock):
    api._assert_user = 'USER'
    api.post({})
    assert post_mock.mock_calls[0].kwargs['data']['assertuser'] == 'USER'


@patch('pymw._api.Path.open', pymw_toml_mock)
@session_post_patch(
    call(url, data={
        'notfilter': '!read', 'meta': 'notifications', 'action': 'query',
        'errorformat': 'plaintext', 'format': 'json', 'formatversion': '2',
        'maxlag': 5,}, files=None),
    {'errors': [{'code': 'login-required', 'text': 'You must be logged in.', 'module': 'query+notifications'}], 'docref': '', 'servedby': 'mw1341'},
    call(url, data={
        'type': 'login', 'meta': 'tokens', 'action': 'query', 'format': 'json',
        'formatversion': '2', 'errorformat': 'plaintext', 'maxlag': 5}, files=None),
    {'batchcomplete': True, 'query': {'tokens': {'logintoken': 'T1'}}},
    call(url, data={
        'action': 'login', 'lgname': 'username@toolname', 'lgpassword':
            'bot_password', 'lgtoken': 'T1', 'format': 'json', 'formatversion':
            '2', 'errorformat': 'plaintext', 'maxlag': 5}, files=None),
    {'login': {'result': 'Success', 'lguserid': 1, 'lgusername': 'username'}},
    call(url, data={
        'notfilter': '!read', 'meta': 'notifications', 'action': 'query',
        'format': 'json', 'formatversion': '2', 'errorformat': 'plaintext',
        'maxlag': 5, 'assertuser': 'username'}, files=None),
    {'batchcomplete': True, 'query': {'notifications': {'list': [], 'continue': None}}},
)
def test_handle_login_required(_, cleared_api):
    r = api.query_meta('notifications', notfilter='!read')
    assert r == {'list': [], 'continue': None}
