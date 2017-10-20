ConsistencyCheck
================

|build|

.. contents:: :local:
   :depth: 2

Compares files on site to files in the dynamo inventory.
This tool requires ``dynamo`` and ``xrdfs`` to be installed separately.

.. _consistency-config-ref:

Running the Tool
++++++++++++++++

A consistency check on a site can be done simply by doing the following::

    from ConsistencyCheck import config, datatypes, getsitecontents, getinventorycontents

    config.CONFIG_FILE = '/path/to/config.json'
    site = 'T2_US_MIT'     # For example

    inventory_listing = getinventorycontents.get_inventory_tree(site)
    remote_listing = getsitecontents.get_site_tree(site)

    datatypes.compare(inventory_listing, remote_listing, 'results')

In this example,
the list of file LFNs in the inventory and not at the site will be in ``results_missing.txt``.
The list of file LFNs at the site and not in the inventory will be in ``results_orphan.txt``.

Configuration
+++++++++++++

A configuration file should be created before pointing to it, like above.
The configuration file for ConsistencyChecks is a JSON or YAML file with the following keys

.. autoanysrc:: phony
   :src: ../ConsistencyCheck/test/config.yml
   :analyzer: shell-script

Configuration parameters can also be quickly overwritten for a given run by
setting an environment variable of the same name.

Production Settings
+++++++++++++++++++

The configuration in production is the following.

.. program-output:: cat ../ConsistencyCheck/prod/consistency_config.json

Comparison Script
-----------------

.. automodule:: compare

Automatic Site Selection
------------------------

To automatically run ``prod/compare.py`` over a few well-deserving sites, use ``prod/run_checks.sh``.

.. autoanysrc:: phony
   :src: ../ConsistencyCheck/prod/run_checks.sh
   :analyzer: perl-script

Reference
+++++++++

The following is a full reference to the submodules inside of the :py:mod:`ConsistencyCheck` module.

config.py
---------

.. automodule:: ConsistencyCheck.config
   :members:

datatypes.py
------------

.. automodule:: ConsistencyCheck.datatypes
   :members:

getsitecontents.py
------------------

.. automodule:: ConsistencyCheck.getsitecontents
   :members:

getinventorycontents.py
-----------------------

.. automodule:: ConsistencyCheck.getinventorycontents
   :members:

.. |build| image:: https://travis-ci.org/dabercro/ConsistencyCheck.svg?branch=master
    :target: https://travis-ci.org/dabercro/ConsistencyCheck
