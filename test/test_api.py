from io import BytesIO
from json import loads as json_loads
from pprint import pformat
from unittest.mock import call, patch, mock_open

from pytest import fixture, raises

# noinspection PyProtectedMember
from pymw import API, LoginError, APIError, _api
# noinspection PyProtectedMember
from pymw._api import get_lgname_lgpass, load_config

url = 'https://www.mediawiki.org/w/api.php'
api = API(url)


TEXT_CONFIG = '''
{
    "https://www.mediawiki.org/w/api.php": {
        "U@T": {"BotPassword": "BP"}
    },
    "https://*.wikipedia.org/w/api.php": {
        "U": {"BotPassword": "P", "limit": 50}
    },
    "https://test.wikipedia.org/w/api.php": {
        "TestUser": {"BotPassword": "TestPass", "limit": 500}
    }
}
'''
CONFIG = json_loads(TEXT_CONFIG)
json_open_mock = mock_open(read_data=TEXT_CONFIG)
patch.object(_api, 'CONFIG', CONFIG).start()


@fixture
def cleared_api():
    api.tokens.clear()
    api._user = None
    return api


def fake_sleep(_):
    return


class FakeResp:
    __slots__ = ('_json', 'headers')

    def __init__(self, json, headers=None):
        self._json = json
        self.headers = {} if headers is None else headers

    def json(self):
        return self._json


def patch_post(obj, attr, call_returns, api_post):
    i = -2

    def side_effect(*args, **kwargs):
        nonlocal i
        i += 2
        if (expected := call_returns[i]) is not any:
            actual_pop = kwargs.pop
            call_pop = (expected_kwargs := expected.kwargs).pop
            if api_post == 1:  # API.post
                assert args == expected.args
            else:  # session.post
                assert not args
                assert expected.args[0] == actual_pop('data')
            assert call_pop('files', None) == actual_pop('files', None)
            assert call_pop('params', None) == actual_pop('params', None)
            assert not kwargs and not expected_kwargs
        return call_returns[i + 1]

    return patch.object(obj, attr, side_effect=side_effect)


def api_post_patch(*call_returns):
    return patch_post(API, 'post', call_returns, True)


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
    return patch_post(api, '_post', call_responses, False)


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
    call({
        'list': ('recentchanges',), 'rcprop': 'timestamp', 'rclimit': 1,
        'action': 'query'}),
    {'batchcomplete': True, 'continue': {
        'rccontinue': '20190908072938|4484663', 'continue': '-||'
    }, 'query': {'recentchanges': [{
        'type': 'log', 'timestamp': '2019-09-08T07:30:00Z'}]}},
    call({
        'list': ('recentchanges',), 'rcprop': 'timestamp', 'rclimit': 1,
        'action': 'query', 'rccontinue': '20190908072938|4484663',
        'continue': '-||'}),
    {'batchcomplete': True, 'query': {'recentchanges': [{
        'type': 'categorize', 'timestamp': '2019-09-08T07:29:38Z'}]}})
def test_recentchanges(_):
    assert [rc for rc in api.list(
        'recentchanges', {'rclimit': 1, 'rcprop': 'timestamp'})] == [
            {'type': 'log', 'timestamp': '2019-09-08T07:30:00Z'},
            {'type': 'categorize', 'timestamp': '2019-09-08T07:29:38Z'}]


@patch('pymw._api.sleep', fake_sleep)
@patch('pymw._api.warning')
@session_post_patch(
    call({
        'action': 'query', 'errorformat': 'plaintext', 'format': 'json',
        'formatversion': '2', 'maxlag': 5, 'meta': 'tokens', 'type': 'watch'
    }),
    {'retry-after': '5'}, {'errors': [{'code': 'maxlag', 'text': 'Waiting for 10.64.16.7: 0.80593395233154 seconds lagged.', 'data': {'host': '10.64.16.7', 'lag': 0.805933952331543, 'type': 'db'}, 'module': 'main'}], 'docref': ..., 'servedby': 'mw1225'},
    call({
        'meta': 'tokens', 'type': 'watch', 'action': 'query', 'format': 'json',
        'formatversion': '2', 'errorformat': 'plaintext', 'maxlag': 5
    }),
    {}, {'batchcomplete': True, 'query': {'tokens': {'watchtoken': '+\\'}}})
def test_maxlag(_, warning_mock, cleared_api):
    tokens = cleared_api.meta('tokens', {'type': 'watch'})
    assert tokens == {'watchtoken': '+\\'}
    warning_mock.assert_called_with('maxlag error (retrying after 5 seconds)')


@api_post_patch(
    call({'action': 'query', 'meta': 'siteinfo', 'siprop': 'protocols'}),
    {'batchcomplete': True, 'query': {'protocols': ['http://', 'https://']}})
def test_siteinfo(post_mock):
    si = api.meta('siteinfo', {'siprop': 'protocols'})
    assert si == {'protocols': ['http://', 'https://']}
    post_mock.assert_called_once()


@api_post_patch(
    call({
        'action': 'query', 'prop': 'langlinks', 'lllimit': 1,
        'titles': ('Main Page',)}),
    {'continue': {'llcontinue': '15580374|bg', 'continue': '||'}, 'query': {
        'pages': [{
            'pageid': 15580374, 'ns': 0, 'title': 'Main Page',
            'langlinks': [{'lang': 'ar', 'title': ''}]}]}},
    call({
        'action': 'query', 'prop': 'langlinks', 'lllimit': 1,
        'titles': ('Main Page',),
        'llcontinue': '15580374|bg', 'continue': '||'}),
    {'batchcomplete': True, 'query': {'pages': [{
        'pageid': 15580374, 'ns': 0, 'title': 'Main Page',
        'langlinks': [{'lang': 'zh', 'title': ''}]}]}})
def test_langlinks(_):
    titles_langlinks = [page_ll for page_ll in api.prop(
        'langlinks', {'titles': 'Main Page', 'lllimit': 1})]
    assert len(titles_langlinks) == 1
    assert titles_langlinks[0] == {'pageid': 15580374, 'ns': 0, 'title': 'Main Page', 'langlinks': [{'lang': 'ar', 'title': ''}, {'lang': 'zh', 'title': ''}]}


@api_post_patch(
    call({'action': 'query', 'prop': 'langlinks', 'titles': ('Main Page',)}),
    {'batchcomplete': True, 'query': {'pages': [{'pageid': 1182793, 'ns': 0, 'title': 'Main Page'}]}, 'limits': {'langlinks': 500}})
def test_lang_links_title_not_exists(post_mock):
    titles_langlinks = [page_ll for page_ll in api.prop(
        'langlinks', {'titles': 'Main Page'})]
    assert len(titles_langlinks) == 1
    post_mock.assert_called_once()
    assert titles_langlinks[0] == {'pageid': 1182793, 'ns': 0, 'title': 'Main Page'}


@api_post_patch(
    call({'action': 'query', 'meta': 'userinfo'}),
    {'batchcomplete': True, 'query': {'userinfo': {'id': 0, 'name': '1.1.1.1', 'anon': True}}})
def test_userinfo(post_mock):
    assert api.meta('userinfo', {}) == {'id': 0, 'name': '1.1.1.1', 'anon': True}
    post_mock.assert_called_once()


@api_post_patch(
    call({'action': 'query', 'meta': 'filerepoinfo', 'friprop': 'displayname'}),
    {'batchcomplete': True, 'query': {'repos': [{'displayname': 'Commons'}, {'displayname': 'Wikipedia'}]}})
def test_filerepoinfo(post_mock):
    assert api.meta('filerepoinfo', {'friprop': 'displayname'}) == \
           [{'displayname': 'Commons'}, {'displayname': 'Wikipedia'}]
    post_mock.assert_called_once()


def test_context_manager():
    a = API('')
    with patch.object(a.session, 'close') as close_mock:
        with a:
            pass
    close_mock.assert_called_once_with()


@session_post_patch(
    any, {}, {'errors': [{'code': 'badtoken', 'text': 'Invalid CSRF token.', 'module': 'patrol'}], 'docref': ..., 'servedby': 'mw1279'})
def test_bad_patrol_token(_):
    api._user = 'x'
    api.tokens['patrol'] = 'T'
    try:
        api.post({'action': 'patrol', 'revid': 1})
    except APIError:
        pass
    else:  # pragma: nocover
        raise AssertionError('APIError was not raised')
    with patch.object(
            API, 'meta', return_value={'patroltoken': 'N'}) as m:
        assert api.tokens['patrol'] == 'N'
    m.assert_called_once_with('tokens', {'type': 'patrol'})


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
    call({
        'action': 'query', 'list': ('logevents',), 'lelimit': 1,
        'leprop': 'timestamp', 'ledir': 'newer',
        'leend': '2004-12-23T18:41:10Z'}),
    {'batchcomplete': True, 'query': {'logevents': [{'timestamp': '2004-12-23T18:41:10Z'}]}})
def test_logevents(post_mock):
    events = [e for e in api.list('logevents', {
        'lelimit': 1, 'leprop': 'timestamp', 'ledir': 'newer',
        'leend': '2004-12-23T18:41:10Z'})]
    assert len(events) == 1
    assert events[0] == {'timestamp': '2004-12-23T18:41:10Z'}
    post_mock.assert_called_once()


@api_post_patch(any, {'batchcomplete': True, 'query': {'normalized': [{'fromencoded': False, 'from': 'a', 'to': 'A'}, {'fromencoded': False, 'from': 'b', 'to': 'B'}], 'pages': [{'pageid': 91945, 'ns': 0, 'title': 'A', 'revisions': [{'revid': 28594859, 'parentid': 28594843, 'minor': False, 'user': '5.119.128.223', 'anon': True, 'timestamp': '2020-03-31T11:38:15Z', 'comment': 'c1'}]}, {'pageid': 91946, 'ns': 0, 'title': 'B', 'revisions': [{'revid': 28199506, 'parentid': 25110220, 'minor': False, 'user': '2.147.31.47', 'anon': True, 'timestamp': '2020-02-08T14:53:12Z', 'comment': 'c2'}]}]}})
def test_revisions_mode13(_):
    assert [
        {'pageid': 91945, 'ns': 0, 'title': 'A', 'revisions': [{'revid': 28594859, 'parentid': 28594843, 'minor': False, 'user': '5.119.128.223', 'anon': True, 'timestamp': '2020-03-31T11:38:15Z', 'comment': 'c1'}]},
        {'pageid': 91946, 'ns': 0, 'title': 'B', 'revisions': [{'revid': 28199506, 'parentid': 25110220, 'minor': False, 'user': '2.147.31.47', 'anon': True, 'timestamp': '2020-02-08T14:53:12Z', 'comment': 'c2'}]}
    ] == [r for r in api.prop('revisions', {'titles': 'a|b'})]


@api_post_patch(
    call({
        'action': 'query', 'prop': 'revisions', 'titles': ('DmazaTest',),
        'rvstart': 'now'}),
    {'batchcomplete': True, 'query': {'pages': [{
        'pageid': 112963, 'ns': 0, 'title': 'DmazaTest', 'revisions': [{
            'revid': 438026, 'parentid': 438023, 'minor': False,
            'user': 'DMaza (WMF)', 'timestamp': '2020-06-25T21:09:52Z',
            'comment': ''
        }, {
            'revid': 438023, 'parentid': 438022, 'minor': False,
            'user': 'DMaza (WMF)', 'timestamp': '2020-06-25T21:08:12Z',
            'comment': ''}, {
            'revid': 438022, 'parentid': 0, 'minor': False,
            'user': 'DMaza (WMF)', 'timestamp': '2020-06-25T21:08:02Z',
            'comment': '1'}]}]}, 'limits': {'revisions': 500}})
def test_revisions_mode2_no_rvlimit(post_mock):  # auto set rvlimit
    assert [
        {'ns': 0, 'pageid': 112963, 'revisions': [{'comment': '', 'minor': False, 'parentid': 438023, 'revid': 438026, 'timestamp': '2020-06-25T21:09:52Z', 'user': 'DMaza (WMF)'}, {'comment': '', 'minor': False, 'parentid': 438022, 'revid': 438023, 'timestamp': '2020-06-25T21:08:12Z', 'user': 'DMaza (WMF)'}, {'comment': '1', 'minor': False, 'parentid': 0, 'revid': 438022, 'timestamp': '2020-06-25T21:08:02Z', 'user': 'DMaza (WMF)'}], 'title': 'DmazaTest'}
    ] == [r for r in api.prop(
        'revisions', {'titles': 'DmazaTest', 'rvstart': 'now'})]
    post_mock.assert_called_once()


@api_post_patch(
    call({'action': 'upload', 'filename': 'FN.jpg'}, files={'file': ('FN.jpg', NotImplemented)}),
    {'upload': {'result': 'Warning', 'warnings': {'exists': 'Test.jpg', 'nochange': {'timestamp': '2020-07-04T07:29:07Z'}}, 'filekey': 'tampered.y27er1.18.jpg', 'sessionkey': 'tampered.y27er1.18.jpg'}})
def test_upload_file(post_mock):
    api._user = 'James Bond'
    api.upload_file(file=NotImplemented, filename='FN.jpg')
    post_mock.assert_called_once()


@patch.object(API, 'login')
def test_upload_file_auto_login(login_mock):
    login_mock.side_effect = NotImplementedError
    api._user = None
    with raises(NotImplementedError):
        api.upload_file(file=NotImplemented, filename='FN.jpg')
    login_mock.assert_called_once_with()


bio0 = BytesIO(b'0')
bio1 = BytesIO(b'1')


@api_post_patch(
    call(
        {'action': 'upload', 'stash': 1, 'offset': 0, 'filename': 'F.jpg', 'filesize': 5039, 'ignorewarnings': True},
        files={'chunk': ('F.jpg', bio0)}),
    {'upload': {'warnings': {'duplicate-archive': 'F.jpg'}, 'result': 'Continue', 'offset': 3000, 'filekey': 'K'}},
    call(
        {'action': 'upload', 'stash': 1, 'offset': 3000, 'filename': 'F.jpg', 'filesize': 5039, 'ignorewarnings': True, 'filekey': 'K'},
        files={'chunk': ('F.jpg', bio1)}),
    {'upload': {'filekey': 'K.jpg', 'imageinfo': {'CENSORED': ...}, 'result': 'Success', 'warnings': {'duplicate-archive': 'T.jpg'}}},
    call(
        {'action': 'upload', 'filename': 'F.jpg', 'ignorewarnings': True, 'filekey': 'K.jpg'}),
    {'upload': {'filename': 'F.jpg', 'imageinfo': {'CENSORED': ...}, 'result': 'Success'}})
def test_upload_chunks(_):
    api._user = 'U'
    result = api.upload_chunks(
        chunks=(b for b in (bio0, bio1)),
        filename='F.jpg',
        filesize=5039,
        ignorewarnings=True)
    assert result == {'filename': 'F.jpg', 'imageinfo': {'CENSORED': ...}, 'result': 'Success'}


@patch('pymw._api.Path.open', json_open_mock)
@patch.object(_api, 'CONFIG', None)
def test_login_config():
    load_config()
    assert _api.CONFIG == CONFIG
    json_open_mock.assert_called_once()


@session_post_patch(any, {}, {})
def test_assert_login(post_mock):
    api._user = 'USER'
    api.post({})
    assert post_mock.mock_calls[0].kwargs['data']['assertuser'] == 'USER'


@session_post_patch(
    call({
        'notfilter': '!read', 'meta': 'notifications', 'action': 'query',
        'errorformat': 'plaintext', 'format': 'json', 'formatversion': '2',
        'maxlag': 5}),
    {'errors': [{'code': 'login-required', 'text': 'You must be logged in.', 'module': 'query+notifications'}], 'docref': ..., 'servedby': 'mw1341'},
    call({
        'type': 'login', 'meta': 'tokens', 'action': 'query', 'format': 'json',
        'formatversion': '2', 'errorformat': 'plaintext', 'maxlag': 5}),
    {'batchcomplete': True, 'query': {'tokens': {'logintoken': 'T1'}}},
    call({
        'action': 'login', 'lgname': 'U@T', 'lgpassword':
            'BP', 'lgtoken': 'T1', 'format': 'json', 'formatversion':
            '2', 'errorformat': 'plaintext', 'maxlag': 5}),
    {'login': {'result': 'Success', 'lguserid': 1, 'lgusername': 'username'}},
    call({
        'notfilter': '!read', 'meta': 'notifications', 'action': 'query',
        'format': 'json', 'formatversion': '2', 'errorformat': 'plaintext',
        'maxlag': 5, 'assertuser': 'username'}),
    {'batchcomplete': True, 'query': {'notifications': {'list': [], 'continue': None}}},
)
def test_handle_login_required(_, cleared_api):
    assert cleared_api.user is None
    r = cleared_api.meta('notifications', {'notfilter': '!read'})
    assert r == {'list': [], 'continue': None}
    assert cleared_api.user == 'username'


@api_post_patch(
    any, {'batchcomplete': True, 'continue': {
        'gapcontinue': '!!', 'continue': 'gapcontinue||'}},
    any, {'batchcomplete': True, 'continue': {
        'gapcontinue': '!!!', 'continue': 'gapcontinue||'}, 'query': {
        'pages': [{'pageid': 3632887, 'ns': 0, 'title': '!!', 'revisions': [{
            'slots': {'main': {
                'contentmodel': 'wikitext', 'contentformat': 'text/x-wiki',
                'content': ...}}}]}]}})
def test_empty_pages_in_prop_query(_):
    # should not raise KeyError: 'query'
    next(api.prop('revisions', {}))


page = {
    'ns': 0,
    'pageid': 8988,
    'revisions': [{'slots': {'main': {
        'content': '', 'contentformat': 'text/x-wiki',
        'contentmodel': 'wikitext'}}}],
    'title': 'E (عدد)'}


@api_post_patch(
    any, {'continue': {
        'continue': 'gapcontinue||', 'gapcontinue': 'Antinatalism',
        'rvcontinue': '1844356|28824240'}, 'limits': {'allpages': 5000},
        'query': {'pages': [page]}},
    any, {'batchcomplete': True, 'continue': {
        'continue': 'gapcontinue||', 'gapcontinue': 'ISO3166-2:AD'},
        'limits': {'allpages': 5000}, 'query': {'pages': [{
            'ns': 0, 'pageid': 8988, 'title': 'E (عدد)'}]}})
def test_prop_complete_first(_):
    # used to give KeyError: 'revisions'
    assert next(api.prop('revisions', {})) is page


@api_post_patch(
    any, {
        'continue': {
            'continue': 'gapcontinue||', 'gapcontinue': 'ISO3166-2:AD'},
        'limits': {'allpages': 5000}, 'query': {
            'pages': [{
                'ns': 0, 'pageid': 8988, 'title': 'E (عدد)'}]}},
    any, {
        'batchcomplete': True,
        'continue': {
            'continue': 'gapcontinue||', 'gapcontinue': 'Antinatalism',
            'rvcontinue': '1844356|28824240'},
        'limits': {'allpages': 5000},
        'query': {'pages': [page]}})
def test_prop_incomplete_first(_):
    # used to give KeyError: 'revisions'
    assert next(api.prop('revisions', {})) == page


c2 = {'continue': 'gapcontinue||', 'gapcontinue': 'ISO3166-2:AD'}
c1 = {
    'continue': 'gapcontinue||', 'gapcontinue': 'Antinatalism',
    'rvcontinue': '1844356|28824240'}


@api_post_patch(
    call({}), {'continue': c1}, call(c1), {'continue': c2}, call(c2), {})
def test_remove_old_continues_from_data(_):
    for _ in api.post_and_continue({}):
        pass


incomplete_page2 = {'ns': 0, 'pageid': 2393444, 'title': 'آ س رایو ناگار'}
page2 = {
    'ns': 0, 'pageid': 2393444, 'revisions': [{'slots': {'main': {
        'content': '', 'contentformat': 'text/x-wiki',
        'contentmodel': 'wikitext'}}}],
    'title': 'آ س رایو ناگار'}


@api_post_patch(
    any, {
        'continue': {
            'continue': 'gapcontinue||',
            'gapcontinue': 'Q_(ابهام\u200cزدایی)',
            'rvcontinue': '2393444|28481387'},
        'limits': {'allpages': 5000}, 'query': {'pages': [incomplete_page2]}},
    any, {
        'continue': {
            'continue': 'gapcontinue||',
            'gapcontinue': 'Q_(ابهام\u200cزدایی)',
            'rvcontinue': '2393444|28481387'},
        'limits': {'allpages': 5000},
        'query': {'pages': [page2]}},
    any, {
        'batchcomplete': True, 'continue': {
            'continue': 'gapcontinue||', 'gapcontinue': 'آئودی_لو_مان_کواترو'},
        'limits': {'allpages': 5000}, 'query': {'pages': [incomplete_page2]}})
def test_complete_in_the_middle_of_batch(_):
    assert next(api.prop('revisions', {})) == page2


page3 = {'ns': 0, 'pageid': 1844356, 'revisions': [{
    'slots': {'main': {
        'content': '', 'contentformat': 'text/x-wiki',
        'contentmodel': 'wikitext'}}}], 'title': 'Getopt'}


@api_post_patch(
    any, {
        'continue': {
            'continue': 'gapcontinue||', 'gapcontinue': 'Antinatalism',
            'rvcontinue': '1844356|28824240'},
        'query': {'pages': [{
            'ns': 0, 'pageid': 1844356, 'title': 'Getopt'}, page2]}},
    any, {
        'batchcomplete': True, 'continue': {
            'continue': 'gapcontinue||', 'gapcontinue': 'ISO3166-2:AD'},
        'query': {'pages': [page3, incomplete_page2]}})
def test_page_in_last_batch(_):
    page = next(api.prop('revisions', {}))
    assert page is page3


@api_post_patch(
    any, {
        'continue': {'llcontinue': '288753|en', 'continue': '||'},
        'query': {'pages': [{
            'pageid': 288753, 'ns': 0, 'title': 'شیران',
            'langlinks': [
                {'lang': 'ar', 'title': 'شيران'},
                {'lang': 'arz', 'title': 'شيران'}]}]}},
    any, {
        'continue': {'llcontinue': '288753|zh-min-nan', 'continue': '||'},
        'query': {'pages': [{
            'pageid': 288753, 'ns': 0, 'title': 'شیران', 'langlinks': [
                {'lang': 'en', 'title': 'Shiran, Ardabil'},
                {'lang': 'ms', 'title': 'Shiran, Ardabil'}]}]}},
    any, {'batchcomplete': True, 'query': {'pages': [
        {'pageid': 288753, 'ns': 0, 'title': 'شیران', 'langlinks': [
            {'lang': 'zh-min-nan', 'title': 'Shiran (Ardabil)'}]}]}})
def test_batch_prop_extend(_):
    assert next(api.prop(
        'langlinks', {'llprop': '', 'lllimit': 2, 'titles': 'شیران'})
    ) == {
        'pageid': 288753, 'ns': 0, 'title': 'شیران', 'langlinks': [
            {'lang': 'ar', 'title': 'شيران'},
            {'lang': 'arz', 'title': 'شيران'},
            {'lang': 'en', 'title': 'Shiran, Ardabil'},
            {'lang': 'ms', 'title': 'Shiran, Ardabil'},
            {'lang': 'zh-min-nan', 'title': 'Shiran (Ardabil)'}]}


def test_url_property():
    assert api.url == url
    with raises(AttributeError):  # can't set attribute
        # noinspection PyPropertyAccess
        api.url = ''


def test_repr():
    assert repr(api) == f'API({repr(url)})'


def test_glob_pattern_load_lgname_lgpass():
    assert get_lgname_lgpass('https://en.wikipedia.org/w/api.php') \
            == get_lgname_lgpass('https://en.wikipedia.org/w/api.php', 'U') \
            == ('U', 'P')


watch_response = {'batchcomplete': True, 'watch': [{'title': '0', 'ns': 0, 'unwatched': True}, {'title': '1', 'ns': 0, 'unwatched': True}]}


@session_post_patch(
    call({
        'action': 'watch', 'titles': '0|1', 'format': 'json',
        'formatversion': '2', 'errorformat': 'plaintext', 'maxlag': 5,
        'token': '+\\', 'unwatch': True}),
    {'errors': [{
        'code': 'notloggedin',
        'text': 'Please log in to view or edit items on your watchlist.',
        'module': 'watch'}], 'docref': ..., 'servedby': 'mw1342'},
    call({
        'type': 'login', 'meta': 'tokens', 'action': 'query', 'format': 'json',
        'formatversion': '2', 'errorformat': 'plaintext', 'maxlag': 5
    }), {'batchcomplete': True, 'query': {'tokens': {
        'logintoken': 'LGT+\\'}}},
    call({
        'action': 'login', 'lgname': 'U@T',
        'lgpassword': 'BP', 'lgtoken': 'LGT+\\',
        'format': 'json', 'formatversion': '2', 'errorformat': 'plaintext',
        'maxlag': 5}),
    {'login': {'result': 'Success', 'lguserid': 1, 'lgusername': 'username'}},
    call({
        'type': 'watch', 'meta': 'tokens', 'action': 'query', 'format': 'json',
        'formatversion': '2', 'errorformat': 'plaintext', 'maxlag': 5,
        'assertuser': 'username'}),
    {'batchcomplete': True, 'query': {'tokens': {'watchtoken': 'LIWT+\\'}}},
    call({
        'action': 'watch', 'titles': '0|1', 'format': 'json',
        'formatversion': '2', 'errorformat': 'plaintext', 'maxlag': 5,
        'token': 'LIWT+\\',
        'unwatch': True, 'assertuser': 'username'}),
    watch_response,)
# assume that watch is not marked as a login-required action
@patch.dict('pymw._api.LOGIN_REQUIRED_ACTIONS', clear=True)
def test_notloggedin_error(_post_mock, cleared_api):
    cleared_api.tokens['watch'] = '+\\'
    r = cleared_api.post({
        'action': 'watch', 'titles': '0|1', 'format': 'json',
        'formatversion': '2', 'errorformat': 'plaintext', 'maxlag': 5,
        'unwatch': True})
    assert r is watch_response


spamblacklist_ok = {'spamblacklist': {'result': 'ok'}}


@session_post_patch(
    any, {'errors': [{
        'code': 'toomanyvalues',
        'text': 'Too many values supplied for parameter "url". The limit is 50.',
        'data': {'limit': 50, 'lowlimit': 50, 'highlimit': 500},
        'module': 'spamblacklist'}], 'docref': ..., 'servedby': 'mw1356'},
    call({
        'action': 'spamblacklist',
        'url': '0|1|2|3|4|5|6|7|8|9|10|11|12|13|14|15|16|17|18|19|20|21|22|23'
               '|24|25|26|27|28|29|30|31|32|33|34|35|36|37|38|39|40|41|42|43|44'
               '|45|46|47|48|49',
        'format': 'json', 'formatversion': '2', 'errorformat': 'plaintext',
        'maxlag': 5}), spamblacklist_ok,
    call({
        'action': 'spamblacklist', 'url': '50', 'format': 'json',
        'formatversion': '2', 'errorformat': 'plaintext', 'maxlag': 5}),
    spamblacklist_ok)
@patch('pymw._api.warning')
def test_handle_toomanyvalues_in_post_and_continue(warning, _, cleared_api):
    for r in cleared_api.post_and_continue({
            'action': 'spamblacklist',
            'url': '0|1|2|3|4|5|6|7|8|9|10|11|12|13|14|15|16|17|18|19|20|21|22'
                   '|23|24|25|26|27|28|29|30|31|32|33|34|35|36|37|38|39|40|41'
                   '|42|43|44|45|46|47|48|49|50',
            'format': 'json', 'formatversion': '2', 'errorformat': 'plaintext',
            'maxlag': 5}):
        assert r is spamblacklist_ok
    warning.assert_called_once_with(
        '`toomanyvalues` error occurred; '
        'trying to split `url` into several API calls.\n'
        'NOTE: sometimes doing this does not make sense.')


@session_post_patch(call({
    'action': 'paraminfo', 'modules': 'query+info|query+categorymembers',
    'format': 'json', 'formatversion': '2', 'errorformat': 'plaintext',
    'maxlag': 5}), {})
def test_iterable_values_to_str(_):
    api.post({
        'action': 'paraminfo',
        'modules': ('query+info', 'query+categorymembers')})


@session_post_patch(
    call({'type': 'login', 'meta': 'tokens', 'action': 'query', 'format': 'json', 'formatversion': '2', 'errorformat': 'plaintext', 'maxlag': 5}),
    {'batchcomplete': True, 'query': {'tokens': {'logintoken': 1}}},
    call({'action': 'login', 'lgname': 'U@T', 'lgpassword': 'BP', 'lgtoken': 1, 'format': 'json', 'formatversion': '2', 'errorformat': 'plaintext', 'maxlag': 5}),
    {'login': {'result': 'Success', 'lguserid': 1, 'lgusername': 'U'}},
    call({'type': 'csrf', 'meta': 'tokens', 'action': 'query', 'format': 'json', 'formatversion': '2', 'errorformat': 'plaintext', 'maxlag': 5, 'assertuser': 'U'}),
    {'batchcomplete': True, 'query': {'tokens': {'csrftoken': 2}}},
    call({'action': 'undelete', 'title': 'a', 'format': 'json', 'formatversion': '2', 'errorformat': 'plaintext', 'maxlag': 5, 'token': 2, 'assertuser': 'U'}),
    (expected_response := {'undelete': {'title': 'A', 'revisions': 1, 'fileversions': 0, 'reason': ''}}))
def test_post_and_continue_with_limited_action_without_limited_param(_, cleared_api):
    assert (expected_response,) == (
        *cleared_api.post_and_continue({'action': 'undelete', 'title': 'a'}),)


@session_post_patch(
    call({
        'action': 'query', 'meta': 'userinfo', 'format': 'json',
        'formatversion': '2', 'errorformat': 'plaintext', 'maxlag': 5}),
    (ui_response := {'batchcomplete': True, 'query': {'userinfo': {
        'id': 0, 'name': '1.2.3.4', 'anon': True}}}))
def test_empty_limited_value(_, cleared_api):
    for r in cleared_api.post_and_continue({
            'action': 'query', 'meta': 'userinfo', 'titles': ''}):
        assert r is ui_response


@api_post_patch(
    call({'action': 'query', 'titles': ('0', '1')}), {},
    call({'action': 'query', 'titles': ('2', '3')}), {},
    call({'action': 'query', 'titles': ('4',)}), {},
)
def test_iterable_limited_value(_, cleared_api):
    cleared_api.limit = 2
    for _ in cleared_api.post_and_continue({
            'action': 'query', 'titles': (f'{t}' for t in range(5))}):
        pass


@api_post_patch(call({'action': 'query'}), {'batchcomplete': True})
def test_none_value_chunk(_, cleared_api):
    for _ in cleared_api.post_and_continue({
            'action': 'query', 'titles': None}):
        pass


@api_post_patch(any, {'login': {'result': 'Success', 'lguserid': 1, 'lgusername': 'TestUser'}})
def test_config_limit(_):
    test_api = API('https://test.wikipedia.org/w/api.php')
    assert test_api.limit == 50
    test_api.tokens['login'] = 'T'
    test_api.login()
    assert test_api.user == 'TestUser'
    assert test_api.limit == 500
