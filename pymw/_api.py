from functools import partial
from pprint import pformat
from typing import Any, BinaryIO, Generator, Iterator, Optional, \
    Union
from logging import warning, debug, info
from pathlib import Path
from time import sleep

from requests import Session, Response
from tomlkit import parse as toml_parse

__version__ = '0.6.0'


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


# noinspection PyShadowingBuiltins
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
            If not provided a default value of f'mwpy/{__version__}'} will be
            used, however that does not fully meet MediaWiki's API etiquette:
            https://www.mediawiki.org/wiki/API:Etiquette#The_User-Agent_header
            See also: https://meta.wikimedia.org/wiki/User-Agent_policy
        """
        self._assert_user = None
        self.maxlag = maxlag
        s = self.session = Session()
        s.headers['User-Agent'] = \
            f'mwpy/{__version__}' if user_agent is None else user_agent
        self.tokens = TokenManager(self)
        self.url = url

    def _handle_api_errors(
        self, data: dict, resp: Response, json: dict
    ) -> dict:
        errors = json['errors']
        for error in errors:
            if (
                handler := getattr(
                    self, f"_handle_{error['code'].replace('-', '_')}_error",
                    None)
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

    def _handle_login_required_error(self, _, data: dict, __):
        warning('"login-required" error occurred')
        self.login()
        return self.post(data)

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
        """Close the current API session and detach TokenManger."""
        del self.tokens.api  # cyclic reference
        self.session.close()

    def login(
        self, lgname: str = None, lgpassword: str = None, **params: Any
    ) -> dict:
        """Log in and set authentication cookies.

        Should only be used in combination with Special:BotPasswords.
        `lgtoken` will be added automatically.

        :param lgname: User name. If not provided will be retrieved from
            ~/.pymw.toml. See README.rst for more info.
        :param lgpassword: Password. If not provided will be retrieved from
            ~/.pymw.toml. See README.rst for more info.

        https://www.mediawiki.org/wiki/API:Login
        """
        if lgpassword is None:
            lgname, lgpassword = load_lgname_lgpass(self.url, lgname)
        params |= {
            'action': 'login', 'lgname': lgname, 'lgpassword': lgpassword,
            'lgtoken': self.tokens['login']}
        json = self.post(params)
        login = json['login']
        result = login['result']
        if result == 'Success':
            self.clear_cache()
            # lgusername == lgname.partition('@')[0]
            self._assert_user = login['lgusername']
            return login
        if result == 'WrongToken':
            # token is outdated?
            info(result)
            del self.tokens['login']
            return self.login(**params)
        raise LoginError(pformat(json))

    def logout(self) -> None:
        """Log out and clear session data.

        https://www.mediawiki.org/wiki/API:Logout
        """
        self.post({'action': 'logout', 'token': self.tokens['csrf']})
        self.clear_cache()
        # action logout returns empty dict on success, thus no return value

    def patrol(self, **params: Any) -> dict:
        """Patrol a page or revision.

        `token` will be added automatically.

        https://www.mediawiki.org/wiki/API:Patrol
        """
        params |= {'action': 'patrol', 'token': self.tokens['patrol']}
        return self.post(params)

    def post(self, data: dict, *, files=None) -> dict:
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
        debug('data:\n\t%s\nfiles:\n\t%s', data, files)
        resp = self.session.post(self.url, data=data, files=files)
        json = resp.json()
        debug('resp.json:\n\t%s', json)
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

    def query(self, params: dict) -> Generator[dict, None, None]:
        """Post an API query and yield results.

        Handle continuations.
        `self.query_list`, `self.query_meta`, and `self.query_prop` should
        be preferred to this method.

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
        params['list'] = list
        for json in self.query(params):
            assert json['batchcomplete'] is True  # T84977#5471790
            for item in json['query'][list]:
                yield item

    def query_meta(self, meta, **params: Any) -> dict:
        """Post a meta query and return the result .

        Note: Some meta queries require special handling. Use `self.query()`
            directly if this method cannot handle it properly and there is no
            other specific method for it.

        https://www.mediawiki.org/wiki/API:Meta
        """
        params['meta'] = meta
        if meta == 'siteinfo':
            for json in self.query(params):
                assert 'continue' not in json
                return json['query']
        for json in self.query(params):
            if meta == 'filerepoinfo':
                meta = 'repos'
            assert 'continue' not in json
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
        params['prop'] = prop
        for json in self.query(params):
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

    def upload(self, data: dict, files=None) -> dict:
        """Post an action=upload request and return the 'upload' key of resp

        Try to login if not already. Add `token` automatically.

        Use `self.upload_file` and `self.upload_chunks`for uploading a file
        or uploading a file in chunks.

        https://www.mediawiki.org/wiki/API:Upload
        """
        if self._assert_user is None:
            self.login()
        data |= {'action': 'upload', 'token': self.tokens['csrf']}
        return self.post(data, files=files)['upload']

    def upload_chunks(
        self, *, chunks: Iterator[BinaryIO], filename: str,
        filesize: Union[int, str], ignorewarnings: bool = None, **params
    ) -> dict:
        """Upload file in chunks using `self.upload`.

        This method handles `offset` and `stash` parameters internally, do NOT
        use them.
        :param chunks: A chuck generator.
        :param filename: Target filename.
        :param filesize: Filesize of entire upload.
        :param ignorewarnings: Ignore any warnings.

        https://www.mediawiki.org/wiki/API:Upload
        """
        # No need to send the comment, text, and other params with every chunk.
        chunk_params = {
            'stash': 1, 'offset': 0, 'filename': filename,
            'filesize': filesize, 'ignorewarnings': ignorewarnings}
        # chunk filename does not matter
        # 'multipart/form-data' header is the default
        files = {'chunk': (filename, next(chunks))}
        upload = self.upload
        upload_chunk = partial(upload, chunk_params, files=files)
        upload = upload_chunk()  # upload the first chunk
        for chunk in chunks:
            chunk_params['offset'] = upload['offset']
            chunk_params['filekey'] = upload['filekey']
            files['chunk'] = (filename, chunk)
            upload = upload_chunk()
        # Final upload using the filekey to commit the upload out of the stash
        params |= {
            'filename': filename, 'ignorewarnings': ignorewarnings,
            'filekey': upload['filekey']}
        return self.upload(params)

    def upload_file(self, *, file: BinaryIO, filename: str, **params) -> dict:
        """Upload a file using `self.upload`.

        :param file: A file-like object to be uploaded using a
            `multipart/form-data` request.
        :param filename: Target filename.

        https://www.mediawiki.org/wiki/API:Upload
        """
        params['filename'] = filename
        return self.upload(params, files={'file': (filename, file)})


def load_lgname_lgpass(api_url, username=None) -> tuple:
    global PARSED_TOML
    if PARSED_TOML is None:
        with (Path('~').expanduser() / '.pymw.toml').open(
            'r', encoding='utf8'
        ) as f:
            pymw_toml = f.read()
        PARSED_TOML = toml_parse(pymw_toml)
    login = PARSED_TOML[api_url]['login'].copy()
    if username is None:
        return *login.popitem(),
    return username, login[username]
