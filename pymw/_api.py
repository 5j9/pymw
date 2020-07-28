from collections import defaultdict
from fnmatch import fnmatch
from functools import partial
from pprint import pformat
from typing import Any, BinaryIO, Generator, Iterator, Literal, Optional, \
    Union
from logging import warning, debug, info
from pathlib import Path
from time import sleep

from requests import Session, Response
from tomlkit import parse as toml_parse

__version__ = '0.6.2.dev0'


TOML_DICT: Optional[dict] = None


LOGIN_REQUIRED_ACTIONS = {
    'patrol', 'upload'
}

# a dictionary from action name to token parameter name and token type
# noinspection PyTypeChecker
ACTION_PARAM_TOKEN: defaultdict[str, Optional[tuple[str, Literal[
    'createaccount', 'csrf', 'deleteglobalaccount', 'login', 'patrol',
    'rollback', 'setglobalaccountstatus', 'userrights', 'watch'
]]]] = defaultdict(lambda: (None, None), {
    'abusefilterunblockautopromote': ('token', 'csrf'),
    'abuselogprivatedetails': ('token', 'csrf'),
    'block': ('token', 'csrf'),
    'centralnoticecdncacheupdatebanner': ('token', 'csrf'),
    'changeauthenticationdata': ('changeauthtoken', 'csrf'),
    'changecontentmodel': ('changeauthtoken', 'csrf'),
    'clientlogin': ('logintoken', 'login'),
    'createaccount': ('createtoken', 'createaccount'),
    'cxdelete': ('token', 'csrf'),
    'cxsuggestionlist': ('token', 'csrf'),
    'cxtoken': ('token', 'csrf'),
    'delete': ('token', 'csrf'),
    'deleteglobalaccount': ('token', 'deleteglobalaccount'),
    'echomarkread': ('token', 'csrf'),
    'echomute': ('token', 'csrf'),
    'edit': ('token', 'csrf'),
    'editmassmessagelist': ('token', 'csrf'),
    'emailuser': ('token', 'csrf'),
    'filerevert': ('token', 'csrf'),
    'globalblock': ('token', 'csrf'),
    'globalpreferenceoverrides': ('token', 'csrf'),
    'globalpreferences': ('token', 'csrf'),
    'globaluserrights': ('token', 'userrights'),
    'import': ('token', 'userrights'),
    'linkaccount': ('linktoken', 'csrf'),
    'login': ('lgtoken', 'login'),
    'logout': ('token', 'csrf'),
    'managetags': ('token', 'csrf'),
    'move': ('token', 'csrf'),
    'pagetriageaction': ('token', 'csrf'),
    'pagetriagetagcopyvio': ('token', 'csrf'),
    'pagetriagetagging': ('token', 'csrf'),
    'patrol': ('token', 'patrol'),
    'protect': ('token', 'csrf'),
    'removeauthenticationdata': ('token', 'csrf'),
    'resetpassword': ('token', 'csrf'),
    'review': ('token', 'csrf'),
    'reviewactivity': ('token', 'csrf'),
    'revisiondelete': ('token', 'csrf'),
    'rollback': ('token', 'rollback'),
    'setglobalaccountstatus': ('token', 'setglobalaccountstatus'),
    'setnotificationtimestamp': ('token', 'csrf'),
    'setpagelanguage': ('token', 'csrf'),
    'stabilize': ('token', 'csrf'),
    'strikevote': ('token', 'csrf'),
    'tag': ('token', 'csrf'),
    'thank': ('token', 'csrf'),
    'transcodereset': ('token', 'csrf'),
    'unblock': ('token', 'csrf'),
    'undelete': ('token', 'csrf'),
    'unlinkaccount': ('token', 'csrf'),
    'upload': ('token', 'csrf'),
    'userrights': ('token', 'userrights'),
    'watch': ('token', 'watch'),
    'wikilove': ('token', 'csrf'),
    'cxpublish': ('token', 'csrf'),
    'cxsave': ('token', 'csrf'),
    'oathvalidate': ('token', 'csrf'),
    'readinglists': ('token', 'csrf'),
    'stashedit': ('token', 'csrf'),
    'ulssetlang': ('token', 'csrf'),
    'visualeditoredit': ('token', 'csrf'),
})


class PYMWError(RuntimeError):
    __slots__ = ()
    pass


class APIError(PYMWError):
    __slots__ = ()
    pass


class LoginError(APIError):
    __slots__ = ()
    pass


class TooManyValuesError(APIError):

    __slots__ = 'error'

    def __init__(self, error):
        self.error = error

    def __getitem__(self, item):
        return self.error[item]


class TokenManager(dict):

    def __init__(self, api: 'API'):
        self.api = api
        super().__init__()

    def __missing__(self, token_type) -> str:
        v = self[token_type] = self.api.query_meta(
            'tokens', type=token_type)[f'{token_type}token']
        return v


# noinspection PyShadowingBuiltins
class API:
    __slots__ = '_url', 'session', 'maxlag', 'tokens', '_user', '_post'

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
        self._user = None
        self.maxlag = maxlag
        s = self.session = Session()
        s.headers['User-Agent'] = \
            f'mwpy/{__version__}' if user_agent is None else user_agent
        self.tokens = TokenManager(self)
        self._url = url
        self._post = partial(s.request, 'POST', url)

    def __repr__(self):
        return f'{type(self).__name__}({self._url!r})'

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
        param, token_type = ACTION_PARAM_TOKEN[error['module']]
        info(f'invalidating {token_type} token cache')
        del self.tokens[token_type]

    def _handle_login_required_error(
        self, _: Response, data: dict, __: dict
    ):
        warning('"login-required" error occurred; trying to login...')
        self.login()
        return self.post(data)

    def _handle_maxlag_error(
        self, resp: Response, data: dict, _
    ) -> dict:
        retry_after = resp.headers['retry-after']
        warning(f'maxlag error (retrying after {retry_after} seconds)')
        sleep(int(retry_after))
        return self.post(data)

    def _handle_notloggedin_error(
        self, _: Response, data: dict, __: dict
    ):
        warning('"notloggedin" error occurred; trying to login...')
        self.login()
        data.pop(ACTION_PARAM_TOKEN[data.get('action')][0], None)
        return self.post(data)

    def _handle_toomanyvalues_error(
        self, resp: Response, data: dict, error: dict
    ):
        raise TooManyValuesError(error)

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
            lgname, lgpassword = load_lgname_lgpass(self._url, lgname)
        params |= {
            'action': 'login', 'lgname': lgname, 'lgpassword': lgpassword,
            'lgtoken': self.tokens['login']}
        json = self.post(params)
        login = json['login']
        result = login['result']
        if result == 'Success':
            self.tokens.clear()
            # lgusername == lgname.partition('@')[0]
            self._user = login['lgusername']
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
        self.post({'action': 'logout'})
        self.tokens.clear()
        self._user = None
        # action logout returns empty dict on success, thus no return value

    def patrol(self, **params: Any) -> dict:
        """Patrol a page or revision.

        `token` will be added automatically.

        https://www.mediawiki.org/wiki/API:Patrol
        """
        params |= {'action': 'patrol'}
        return self.post(params)

    def _prepare_action(self, /, data: dict):
        if (action := data.get('action')) is None:
            return
        # login
        if action in LOGIN_REQUIRED_ACTIONS:
            if self._user is None:
                self.login()
        # token
        param, token_type = ACTION_PARAM_TOKEN[action]
        if param is not None:
            data.setdefault(param, self.tokens[token_type])

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
        self._prepare_action(data)
        if self._user is not None:
            data['assertuser'] = self._user
        debug('data:\n\t%s\nfiles:\n\t%s', data, files)
        resp = self._post(data=data, files=files)
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
        prev_continue = None
        while True:
            try:
                json = self.post(data)
            except TooManyValuesError as e:
                param = (text := e['text'])[  # T258469
                    (start := (find := text.find)('"') + 1):find('"', start)]
                warning(
                    f'`toomanyvalues` error occurred; trying to split '
                    f'`{param}` into several API calls.\n'
                    # e.g. on `templatesandboxprefix` of `parse` module.
                    f"NOTE: sometimes doing this does not make sense.")
                param_values = data[param].split('|')
                limit = e['data']['limit']
                for i in range(0, len(param_values), limit):
                    data[param] = '|'.join(param_values[i:i + limit])
                    yield from self.post_and_continue(data)
                return  # pragma: nocover
            yield json
            if (continue_ := json.get('continue')) is None:
                return
            if prev_continue is None:
                data |= (prev_continue := continue_)
                continue
            # Remove or update any prev_continue key in data.
            for k in prev_continue.keys() - continue_.keys():
                del data[k]
            data |= (prev_continue := continue_)

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
        params['prop'] = prop
        batch = None
        for json in self.query(params):
            if (query := json.get('query')) is None:
                continue
            pages = query['pages']
            if 'batchcomplete' in json:
                if batch is None:
                    for page in pages:
                        yield page
                    continue
                for page, batch_page in zip(pages, batch):
                    if (pp := page.get(prop)) is not None:
                        if (bp := batch_page.setdefault(prop, pp)) is not pp:
                            bp += pp
                            yield batch_page
                        else:
                            yield page
                    else:
                        yield batch_page
                batch = None
                continue
            if batch is None:
                batch = pages
                continue
            for page, batch_page in zip(pages, batch):
                if (pp := page.get(prop)) is not None:
                    if (bp := batch_page.setdefault(prop, pp)) is not pp:
                        bp += pp

    def upload(self, data: dict, files=None) -> dict:
        """Post an action=upload request and return the 'upload' key of resp

        Try to login if not already. Add `token` automatically.

        Use `self.upload_file` and `self.upload_chunks`for uploading a file
        or uploading a file in chunks.

        https://www.mediawiki.org/wiki/API:Upload
        """
        data['action'] = 'upload'
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

    @property
    def url(self):
        return self._url

    @property
    def user(self):
        return self._user


def load_lgname_lgpass(api_url, username=None) -> tuple[str, str]:
    global TOML_DICT
    if TOML_DICT is None:
        with (Path('~').expanduser() / '.pymw.toml').open(
            'r', encoding='utf8'
        ) as f:
            pymw_toml = f.read()
        TOML_DICT = dict(toml_parse(pymw_toml))
    if (url_config := TOML_DICT.get(api_url)) is None:
        for url_pattern, url_config in TOML_DICT.items():
            if fnmatch(api_url, url_pattern):
                break
    login = url_config['login']
    if username is None:
        return next(login.items())
    return username, login[username]
