.. image:: https://badge.fury.io/py/pymw.svg
    :target: https://badge.fury.io/py/pymw
.. image:: https://travis-ci.org/5j9/pymw.svg?branch=master
    :target: https://travis-ci.org/5j9/pymw
.. image:: https://codecov.io/gh/5j9/pymw/branch/master/graph/badge.svg
  :target: https://codecov.io/gh/5j9/pymw

Yet another MediaWiki client library for Python. It's not stable yet and it requires Python 3.9+!

Installation
------------
.. code-block:: bash

    pip install pymw

Usage
-----
To avoid directly providing username and password for login calls create a ``.pymw.json`` file in your home directory with the following format:

.. code-block:: json

    {
        "https://test.wikipedia.org/w/api.php": {
            "<Username@Special:BotPasswords>": {
                "BotPassword": "<BotPassword>"
            },
            "<Username2>": {
                "BotPassword": "<BotPassword>",
                "limit": 500
            }
        },
        "https://*.wikipedia.org/w/api.php": {
            "<Username>": {
                "BotPassword": "<BotPassword>"
            }
        }
    }

As you can see, glob patterns are supported.

Notable features
----------------
- Has a ``post_and_continue`` method that can handle `continuations`_.
- Parameter values can be ``str`` or any Python iterable. Iterable values that are not an ``str`` instance will be converted to a pipe-joined ``str`` before being sent.
- The ``post_and_continue`` method automatically breaks a value that has too many items in it into several API calls according the API limit for the current user and yields the results. (Currently this feature works only if there is just one violating parameter. The algorithm might be improved in the future to handle more complex situations.)
- ``prop`` method handles batchcomplete_ signals for prop queries and yields the results as soon as a batch is complete.
- Configurable maxlag_. Waits as the  API recommends and then retries.
- Automatically tries to login before performing actions that are known to require login.
- Automatically tries to login if an API call returns ``login-required`` error (requires username and password to be set in ``~/.pymw.json``).
- Some convenient methods for accessing common API calls, e.g. for login_ and upload_.
- Lightweight. ``pymw`` is a thin wrapper. Method signatures are very similar to the parameters in an actual API URL. You can consult MediaWiki's documentation if in doubt about what a parameter does.
- The ``post_and_continue`` method can handle *most* ``toomanyvalues`` errors by automatically splitting the violating parameter into several API calls. (not a feature to rely on in production, but nice to have during a console session for example.)
- Supports setting a custom `User-Agent header`_ for each ``API`` instance.

.. _MediaWiki: https://www.mediawiki.org/
.. _User-Agent header: https://www.mediawiki.org/wiki/API:Etiquette#The_User-Agent_header
.. _continuations: https://www.mediawiki.org/wiki/API:Query#Example_4:_Continuing_queries
.. _batchcomplete: https://www.mediawiki.org/wiki/API:Query#Example_5:_Batchcomplete
.. _recentchanges: https://www.mediawiki.org/wiki/API:RecentChanges
.. _login: https://www.mediawiki.org/wiki/API:Login
.. _siteinfo: https://www.mediawiki.org/wiki/API:Siteinfo
.. _maxlag: https://www.mediawiki.org/wiki/Manual:Maxlag_parameter
.. _Python: https://www.python.org/
.. _upload: https://www.mediawiki.org/wiki/API:Upload
