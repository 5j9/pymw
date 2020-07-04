#!/usr/bin/env bash
from re import search
from subprocess import check_call, check_output

from path import Path
from parver import Version


repo = Path(__file__).parent.parent
repo.cd()

version_file = 'pymw/_api.py'


def ask_new_version(old_version: Version) -> Version:
    assert old_version.is_devrelease
    major = old_version.bump_release(index=0).base_version()
    minor = old_version.bump_release(index=1).base_version()
    patch = old_version.bump_release(index=2).base_version()
    index = int(input(
        f'Current version is:\n'
        f'  {old_version}\n'
        'Enter release type:\n'
        f'   0: major: {major}\n'
        f'   1: minor: {minor}\n'
        f'   2: patch: {patch}\n'))
    return (major, minor, patch)[index]


def update_version(
    old_version: Version = None, new_version: Version = None
) -> Version:
    with (repo / version_file).open('br+') as f:
        content = f.read()
        old_bytes_version = search(rb"__version__ = '(.*)'", content)[1]
        if old_version is None:
            old_version = Version.parse(old_bytes_version.decode())
        if new_version is None:
            new_version = ask_new_version(old_version)
        f.seek(0)
        f.write(content.replace(old_bytes_version, str(new_version).encode(), 1))
        f.truncate()
    return new_version


def commit(v_version: str):
    check_call(('git', 'commit', '--all', f'--message=release: {v_version}'))


def commit_and_tag_version_change(release_version: Version):
    v_version = f'v{release_version}'
    commit(v_version)
    check_call(('git', 'tag', '-a', v_version, '-m', ''))


assert check_output(('git', 'branch', '--show-current')) == b'master\n'
assert check_output(('git', 'status', '--porcelain')) == b''


release_version = update_version()
commit_and_tag_version_change(release_version)


try:
    check_call(('python', 'setup.py', 'sdist', 'bdist_wheel'))
    check_call(('twine', 'upload', 'dist/*'))
finally:
    for d in ('dist', 'build'):
        (repo / d).rmtree()

# prepare next dev0
new_dev_version = release_version.bump_release(index=2).bump_dev()
update_version(release_version, new_dev_version)
commit(f'v{str(new_dev_version)}')

check_call(('git', 'push'))
