.. image:: https://badge.fury.io/py/pymw.svg
    :target: https://badge.fury.io/py/pymw
.. image:: https://travis-ci.org/5j9/pymw.svg?branch=master
    :target: https://travis-ci.org/5j9/pymw
.. image:: https://codecov.io/gh/5j9/pymw/branch/master/graph/badge.svg
  :target: https://codecov.io/gh/5j9/pymw

Another personal pet project of mine. It requires Python 3.9+!

Installation
------------
.. code-block:: bash

    pip install pymw

Usage
-----
Create a ``.pymw.toml`` file in your home directory with the following content format to avoid directly providing username and password for login calls:

.. code-block:: toml

    # The configuration file for pymw python library.
    version = 1

    ['https://test.wikipedia.org/w/api.php'.login]
    '<Username@Special:BotPasswords>' = '<BotPassword>'


Notable features
----------------
- Supports setting a custom `User-Agent header`_ for each ``API`` instance.
- Handles `query continuations`_.
- Handles batchcomplete_ signals for prop queries and yeilds the results as soon as a batch is complete.
- Configurable maxlag_. Waits as the  API recommends and then retries.
- Some convenient methods for accessing common API calls, e.g. for login_, upload_.
- Automatically tries to login if an API call returns ``login-required`` error (requires username and password to be set in ``~/.pymw.toml``).
- Lightweight. ``pymw`` is a thin wrapper. Method signatures are very similar to the parameters in an actual API URL. You can consult MediaWiki's documentation if in doubt about what a parameter does.

.. _MediaWiki: https://www.mediawiki.org/
.. _User-Agent header: https://www.mediawiki.org/wiki/API:Etiquette#The_User-Agent_header
.. _query continuations: https://www.mediawiki.org/wiki/API:Query#Example_4:_Continuing_queries
.. _batchcomplete: https://www.mediawiki.org/wiki/API:Query#Example_5:_Batchcomplete
.. _recentchanges: https://www.mediawiki.org/wiki/API:RecentChanges
.. _login: https://www.mediawiki.org/wiki/API:Login
.. _siteinfo: https://www.mediawiki.org/wiki/API:Siteinfo
.. _maxlag: https://www.mediawiki.org/wiki/Manual:Maxlag_parameter
.. _Python: https://www.python.org/
.. _upload: https://www.mediawiki.org/wiki/API:Upload
