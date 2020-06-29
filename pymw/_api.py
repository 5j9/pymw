from pprint import pformat
from typing import Any, Generator, Optional
from logging import warning, debug, info
from pathlib import Path
from time import sleep

from requests import Session, Response
from tomlkit import parse as toml_parse

__version__ = '0.4.dev0'


PARSED_TOML: Optional[str] = None


class PYMWError(RuntimeError):
    pass


class APIError(PYMWError):
    pass


class LoginError(PYMWError):
    pass


class TokenManager(dict):

    def __init__(self, api: 'API'):
        self.api = api
        super().__init__()

    def __missing__(self, key):
        v = self[key] = self.api.query_meta('tokens', type=key)[f'{key}token']
        return v


# noinspection PyShadowingBuiltins,PyAttributeOutsideInit
class API:
    __slots__ = 'url', 'session', 'maxlag', 'tokens', '_assert_user'

    def __enter__(self) -> 'API':
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def __init__(
        self, url: str, user_agent: str = None, maxlag: int = 5,
    ) -> None:
        """Initialize API object.

        :param url: the api's url, e.g.
            https://en.wikipedia.org/w/api.php
        :param maxlag: see:
            https://www.mediawiki.org/wiki/Manual:Maxlag_parameter
        :param user_agent: A string to be used as the User-Agent header value.
            If not provided a default value of f'mwpy/v{__version__}'} will be
            used, however that's not enough most of the time. see:
            https://meta.wikimedia.org/wiki/User-Agent_policy and
            https://www.mediawiki.org/wiki/API:Etiquette#The_User-Agent_header
        """
        self._assert_user = None
        self.maxlag = maxlag
        s = self.session = Session()
        s.headers.update({'User-Agent': user_agent or f'mwpy/v{__version__}'})
        self.tokens = TokenManager(self)
        self.url = url

    def _handle_api_errors(
        self, data: dict, resp: Response, json: dict
    ) -> dict:
        errors = json['errors']
        for error in errors:
            if (
                handler := getattr(
                    self, f'_handle_{error["code"]}_error', None)
            ) is not None and (
                handler_result := handler(resp, data, error)
            ) is not None:
                # https://youtrack.jetbrains.com/issue/PY-39262
                # noinspection PyUnboundLocalVariable
                return handler_result
        raise APIError(errors)

    def _handle_badtoken_error(
        self, _: Response, __: dict, error: dict
    ) -> None:
        if error['module'] == 'patrol':
            info('invalidating patrol token cache')
            del self.tokens['patrol']

    def _handle_maxlag_error(
        self, resp: Response, data: dict, _
    ) -> dict:
        retry_after = resp.headers['retry-after']
        warning(f'maxlag error (retrying after {retry_after} seconds)')
        sleep(int(retry_after))
        return self.post(data)

    def clear_cache(self) -> None:
        """Clear cached values."""
        self.tokens.clear()
        self._assert_user = None

    def close(self) -> None:
        """Close the current API session."""
        del self.tokens.api  # cyclic reference
        self.session.close()

    def filerepoinfo(self, **kwargs: Any) -> dict:
        """https://www.mediawiki.org/wiki/API:Filerepoinfo"""
        return self.query_meta('filerepoinfo', **kwargs)

    def langlinks(
        self, lllimit: int = 'max', **kwargs: Any
    ) -> Generator[dict, None, None]:
        for page_llink in self.query_prop(
            'langlinks', lllimit=lllimit, **kwargs
        ):
            yield page_llink

    def login(
        self, lgname: str = None, lgpassword: str = None, **kwargs: Any
    ) -> None:
        """https://www.mediawiki.org/wiki/API:Login

        `lgtoken` will be added automatically.
        """
        if lgpassword is None:
            lgname, lgpassword = load_lgname_lgpass(self.url, lgname)
        json = self.post({
            'action': 'login',
            'lgname': lgname,
            'lgpassword': lgpassword,
            'lgtoken': self.tokens['login'],
            **kwargs})
        result = json['login']['result']
        if result == 'Success':
            self.clear_cache()
            self._assert_user = lgname
            return
        if result == 'WrongToken':
            # token is outdated?
            info(result)
            del self.tokens['login']
            return self.login(lgname, lgpassword, **kwargs)
        raise LoginError(pformat(json))

    def logout(self) -> None:
        """https://www.mediawiki.org/wiki/API:Logout"""
        self.post({'action': 'logout', 'token': self.tokens['csrf']})
        self.clear_cache()

    def patrol(self, **kwargs: Any) -> dict:
        """https://www.mediawiki.org/wiki/API:Patrol

        `token` will be added automatically.
        """
        return self.post(
            {'action': 'patrol', 'token': self.tokens['patrol'], **kwargs})

    def post(self, data: dict) -> dict:
        """Post a request to MW API and return the json response.

        Force format=json, formatversion=2, errorformat=plaintext, and
        maxlag=self.maxlag.
        Warn about warnings and raise errors as APIError.
        """
        data |= {
            'format': 'json',
            'formatversion': '2',
            'errorformat': 'plaintext',
            'maxlag': self.maxlag}
        if self._assert_user is not None:
            data['assertuser'] = self._assert_user
        debug('post data: %s', data)
        resp = self.session.post(self.url, data=data)
        json = resp.json()
        debug('json response: %s', json)
        if 'warnings' in json:
            warning(pformat(json['warnings']))
        if 'errors' in json:
            return self._handle_api_errors(data, resp, json)
        return json

    def post_and_continue(self, data: dict) -> Generator[dict, None, None]:
        """Yield and continue post results until all the data is consumed."""
        if 'rawcontinue' in data:
            raise NotImplementedError(
                'rawcontinue is not implemented for query method')
        while True:
            json = self.post(data)
            continue_ = json.get('continue')
            yield json
            if continue_ is None:
                return
            data |= continue_

    def query(self, **params) -> Generator[dict, None, None]:
        """Post an API query and yield results.

        Handle continuations.

        https://www.mediawiki.org/wiki/API:Query
        """
        # todo: titles or pageids is limited to 50 titles per query,
        #  or 500 for those with the apihighlimits right.
        params['action'] = 'query'
        yield from self.post_and_continue(params)

    def query_list(
        self, list: str, **params: Any
    ) -> Generator[dict, None, None]:
        """Post a list query and yield the results.

        https://www.mediawiki.org/wiki/API:Lists
        """
        for json in self.query(list=list, **params):
            assert json['batchcomplete'] is True  # T84977#5471790
            for item in json['query'][list]:
                yield item

    def query_meta(self, meta, **kwargs: Any) -> dict:
        """Post a meta query and return the result .

        Note: Some meta queries require special handling. Use `self.query()`
            directly if this method cannot handle it properly and there is no
            other specific method for it.

        https://www.mediawiki.org/wiki/API:Meta
        """
        if meta == 'siteinfo':
            for json in self.query(meta='siteinfo', **kwargs):
                assert 'batchcomplete' in json
                assert 'continue' not in json
                return json['query']
        for json in self.query(meta=meta, **kwargs):
            if meta == 'filerepoinfo':
                meta = 'repos'
            assert json['batchcomplete'] is True
            return json['query'][meta]

    def query_prop(
        self, prop: str, **params: Any
    ) -> Generator[dict, None, None]:
        """Post a prop query, handle batchcomplete, and yield the results.

        https://www.mediawiki.org/wiki/API:Properties
        """
        batch = {}
        batch_get = batch.get
        batch_clear = batch.clear
        batch_setdefault = batch.setdefault
        for json in self.query(prop=prop, **params):
            pages = json['query']['pages']
            if 'batchcomplete' in json:
                if not batch:
                    for page in pages:
                        yield page
                    continue
                for page in pages:
                    page_id = page['pageid']
                    batch_page = batch_get(page_id)
                    if batch_page is None:
                        yield page
                    batch_page[prop] += page[prop]
                    yield batch_page
                batch_clear()
                continue
            for page in pages:
                page_id = page['pageid']
                batch_page = batch_setdefault(page_id, page)
                if page is not batch_page:
                    batch_page[prop] += page[prop]

    def recentchanges(
        self, rclimit: int = 'max', **kwargs: Any
    ) -> Generator[dict, None, None]:
        """https://www.mediawiki.org/wiki/API:RecentChanges"""
        # Todo: somehow support rcgeneraterevisions
        yield from self.query_list(
            list='recentchanges', rclimit=rclimit, **kwargs)

    def revisions(self, **kwargs) -> dict:
        """https://www.mediawiki.org/wiki/API:Revisions

        If in mode 2 and 'rvlimit' is not specified, 'max' will be used.
        """
        if 'rvlimit' not in kwargs and (
            'rvstart' in (keys := kwargs.keys())
            or 'rvend' in keys or 'rvlimit' in keys
        ):  # Mode 2: Get revisions for one given page
            kwargs['rvlimit'] = 'max'
        for revisions in self.query_prop('revisions', **kwargs):
            yield revisions

    def siteinfo(self, **kwargs: Any) -> dict:
        """https://www.mediawiki.org/wiki/API:Siteinfo"""
        return self.query_meta('siteinfo', **kwargs)

    def userinfo(self, **kwargs) -> dict:
        """https://www.mediawiki.org/wiki/API:Userinfo"""
        return self.query_meta('userinfo', **kwargs)

    def logevents(
        self, lelimit: int = 'max', **kwargs
    ) -> Generator[dict, None, None]:
        """https://www.mediawiki.org/wiki/API:Logevents"""
        yield from self.query_list('logevents', lelimit=lelimit, **kwargs)


def load_lgname_lgpass(api_url, username=None) -> tuple:
    global PARSED_TOML
    if PARSED_TOML is None:
        with (Path('~').expanduser() / '.pymw.toml').open(
            'r', encoding='utf8'
        ) as f:
            pymw_toml = f.read()
        PARSED_TOML = toml_parse(pymw_toml)
    login = PARSED_TOML[api_url]['login']
    if username is None:
        return *login.popitem(),
    return username, login[username]
